/*++
    Sockwiz is a multi-platform sockets library which provides a simplified
    I/O model.
--*/

#ifdef WINBUILD

#include <winsock2.h>
#include <ws2tcpip.h>
#include <mstcpip.h>
#include <mswsock.h>
#include <assert.h>

#else // WINBUILD

#define _GNU_SOURCE
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <sys/epoll.h>
#include <arpa/inet.h>
#include <sched.h>
#include <errno.h>
#include <assert.h>

typedef int SOCKET;
#define SOCKET_ERROR (-1)
#define INVALID_SOCKET (-1)
#define closesocket close
#define WSAGetLastError() errno

#endif // !WINBUILD

#include <stdio.h>
#include <stdlib.h>

#include "sockwiz.h"

FILE *sockwiz_output_stream = NULL;

#define ERRORMSG(msg, e) fprintf(sockwiz_output_stream, "ERROR at %s:%d %s %s %d\n", __FILE__, __LINE__, __FUNCTION__, msg, e)
#define ABORTMSG(msg, e)                                                                                   \
  {                                                                                                        \
    fprintf(sockwiz_output_stream, "ABORT at %s:%d %s %s %d\n", __FILE__, __LINE__, __FUNCTION__, msg, e); \
    exit(-1);                                                                                              \
  }

#define ASYNC_RESULT_CACHE_SIZE 16

#define SOCKWIZ_ERROR_ENCODE(x) x // TODO: check/sanitize/convert OS-specific error codes

struct _SOCKWIZ_SOCK;

typedef struct _SOCKWIZ_ASYNC_WAITER
{
#ifdef WINBUILD

  HANDLE iocp_handle;

#else // WINBUILD

  int epoll_handle;

  struct _SOCKWIZ_SOCK *closing_head;
  struct _SOCKWIZ_SOCK **closing_tail;

#endif // !WINBUILD

  int cache_index;
  int cache_count;
  sockwiz_async_result cache[ASYNC_RESULT_CACHE_SIZE];
} SOCKWIZ_ASYNC_WAITER;

typedef struct _SOCKWIZ_SOCK
{

  sockwiz_socket_type type;

  u_int connecting : 1;

#ifndef WINBUILD

  u_int first_epoll_issued : 1;

  struct _SOCKWIZ_SOCK *next;

#endif // !WINBUILD

  int address_family;
  SOCKWIZ_ASYNC_WAITER *async_waiter;

  SOCKET os_socket;

  union
  {
    struct
    {
#ifdef WINBUILD

      OVERLAPPED read_ov;
      OVERLAPPED write_ov;

#else // WINBUILD

      char *pending_read_buf;
      int pending_read_buf_len;
      struct sockaddr *pending_read_address;

      char *pending_write_buf;
      int pending_write_buf_len;
      struct sockaddr *pending_write_address;

#endif // !WINBUILD

    } datasocket;

    struct
    {
      struct _SOCKWIZ_SOCK *pending_accept_sockobj;
      struct sockaddr *pending_accept_address;

#ifdef WINBUILD

      OVERLAPPED accept_ov;
      UCHAR address_buffer[sizeof(struct sockaddr_in6) + 16];

#endif // WINBUILD

    } listensocket;
  };

} SOCKWIZ_SOCK;

static int
get_sockaddr_length(
    int address_family)
{
  switch (address_family)
  {
  case AF_INET:
    return sizeof(struct sockaddr_in);
  case AF_INET6:
    return sizeof(struct sockaddr_in6);
  default:
    return 0;
  }
}

static sockwiz_socket_t
get_sockhandle(
    SOCKWIZ_SOCK *sockobj)
{
  return (sockwiz_socket_t)(sockobj + 1);
}

static SOCKWIZ_SOCK *
get_sockobj(
    sockwiz_socket_t sock)
{
  return (((SOCKWIZ_SOCK *)sock) - 1);
}

static void
async_waiter_close_internal(
    SOCKWIZ_ASYNC_WAITER *async_waiter)
{
  assert(async_waiter->cache_count == 0);

#ifdef WINBUILD

  if (async_waiter->iocp_handle != NULL)
  {
    CloseHandle(async_waiter->iocp_handle);
    async_waiter->iocp_handle = NULL;
  }

#else // WINBUILD

  assert(async_waiter->closing_head == NULL);
  assert(async_waiter->closing_tail == &async_waiter->closing_head);

  if (async_waiter->epoll_handle != 0 && async_waiter->epoll_handle != -1)
  {
    close(async_waiter->epoll_handle);
  }

  async_waiter->epoll_handle = 0;

#endif // !WINBUILD

  free(async_waiter);
}

static int
set_socket_nonblocking(
    SOCKET s)
{
  int rc;
  int on = 1;

#ifdef WINBUILD

  rc = ioctlsocket(s, FIONBIO, (u_long *)&on);

#else // WINBUILD

  rc = ioctl(s, FIONBIO, &on);

#endif // !WINBUILD

  return rc;
}

#ifdef WINBUILD

static LPFN_CONNECTEX fn_connect_ex = NULL;
static LPFN_DISCONNECTEX fn_disconnect_ex = NULL;
static LPFN_ACCEPTEX fn_accept_ex = NULL;
static LPFN_GETACCEPTEXSOCKADDRS fn_get_sockaddrs = NULL;

static void
get_connectex_fn(
    void)
{

  SOCKET s;
  GUID guid = WSAID_CONNECTEX;
  DWORD bytes;
  int err;

  if (fn_connect_ex != NULL)
  {
    return;
  }

  s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);

  if (s == INVALID_SOCKET)
  {
    err = WSAGetLastError();
    goto exit;
  }

  if (WSAIoctl(s,
               SIO_GET_EXTENSION_FUNCTION_POINTER,
               &guid,
               sizeof(guid),
               &fn_connect_ex,
               sizeof(fn_connect_ex),
               &bytes,
               NULL,
               NULL) == SOCKET_ERROR)
  {
    err = WSAGetLastError();
    goto exit;
  }

  err = SOCKWIZ_SUCCESS;

exit:

  if (s != INVALID_SOCKET)
  {
    closesocket(s);
  }

  if (err != SOCKWIZ_SUCCESS)
  {
    ABORTMSG("ConnectEx query", err)
  }
}

static void
get_disconnectex_fn(
    void)
{

  SOCKET s;
  GUID guid = WSAID_DISCONNECTEX;
  DWORD bytes;
  int err;

  if (fn_disconnect_ex != NULL)
  {
    return;
  }

  s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);

  if (s == INVALID_SOCKET)
  {
    err = WSAGetLastError();
    goto exit;
  }

  if (WSAIoctl(s,
               SIO_GET_EXTENSION_FUNCTION_POINTER,
               &guid,
               sizeof(guid),
               &fn_disconnect_ex,
               sizeof(fn_disconnect_ex),
               &bytes,
               NULL,
               NULL) == SOCKET_ERROR)
  {
    err = WSAGetLastError();
    goto exit;
  }

  err = SOCKWIZ_SUCCESS;

exit:

  if (s != INVALID_SOCKET)
  {
    closesocket(s);
  }

  if (err != SOCKWIZ_SUCCESS)
  {
    ABORTMSG("DisconnectEx query", err)
  }
}

static void
get_acceptex_fn(
    void)
{

  SOCKET s;
  GUID guid1 = WSAID_GETACCEPTEXSOCKADDRS;
  GUID guid2 = WSAID_ACCEPTEX;
  DWORD bytes;
  int err;

  if (fn_accept_ex != NULL)
  {
    assert(fn_get_sockaddrs != NULL);
    return;
  }

  s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);

  if (s == INVALID_SOCKET)
  {
    err = WSAGetLastError();
    goto exit;
  }

  if (WSAIoctl(s,
               SIO_GET_EXTENSION_FUNCTION_POINTER,
               &guid1,
               sizeof(guid1),
               &fn_get_sockaddrs,
               sizeof(fn_get_sockaddrs),
               &bytes,
               NULL,
               NULL) == SOCKET_ERROR)
  {
    err = WSAGetLastError();
    goto exit;
  }

  MemoryBarrier();

  if (WSAIoctl(s,
               SIO_GET_EXTENSION_FUNCTION_POINTER,
               &guid2,
               sizeof(guid2),
               &fn_accept_ex,
               sizeof(fn_accept_ex),
               &bytes,
               NULL,
               NULL) == SOCKET_ERROR)
  {
    err = WSAGetLastError();
    goto exit;
  }

  err = SOCKWIZ_SUCCESS;

exit:

  if (s != INVALID_SOCKET)
  {
    closesocket(s);
  }

  if (err != SOCKWIZ_SUCCESS)
  {
    ABORTMSG("AcceptEx query", err)
  }
}

static void
get_acceptex_remoteaddress(
    SOCKWIZ_SOCK *listensockobj,
    struct sockaddr *remote_address)
{
  if (remote_address != NULL)
  {
    struct sockaddr *ra;
    int ralen;

    fn_get_sockaddrs(
        listensockobj->listensocket.address_buffer,
        0, 0, sizeof(listensockobj->listensocket.address_buffer),
        NULL, NULL, &ra, &ralen);

    assert(ralen == get_sockaddr_length(listensockobj->address_family));

    memcpy(remote_address, ra, ralen);
  }
}

int update_accept_context(
    SOCKET acceptsocket,
    SOCKET listensocket)
{
  int rc;

  if (setsockopt(
          acceptsocket,
          SOL_SOCKET,
          SO_UPDATE_ACCEPT_CONTEXT,
          (char *)&listensocket,
          sizeof(listensocket)) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("SO_UPDATE_ACCEPT_CONTEXT", rc);
  }
  else
  {
    rc = SOCKWIZ_SUCCESS;
  }

  return rc;
}

int update_connect_context(
    SOCKET connectsocket)
{
  int rc;

  if (setsockopt(
          connectsocket,
          SOL_SOCKET,
          SO_UPDATE_CONNECT_CONTEXT,
          NULL,
          0) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("SO_UPDATE_CONNECT_CONTEXT", rc);
  }
  else
  {
    rc = SOCKWIZ_SUCCESS;
  }

  return rc;
}

static int
async_waiter_wait_iocp(
    SOCKWIZ_ASYNC_WAITER *async_waiter,
    int timeout)
{
  int rc;
  BOOL retval;
  OVERLAPPED_ENTRY ovea[ASYNC_RESULT_CACHE_SIZE];
  ULONG num_entries;

  assert(async_waiter->cache_count == 0);
  assert(async_waiter->cache_index == 0);

  retval = GetQueuedCompletionStatusEx(
      async_waiter->iocp_handle,
      ovea,
      ASYNC_RESULT_CACHE_SIZE,
      &num_entries,
      (DWORD)timeout,
      FALSE);

  if (retval == FALSE)
  {
    //
    // The only legitimate failure case for GQCSEx is timeout in this case.
    //
    rc = SOCKWIZ_TIMEOUT;
  }
  else
  {
    ULONG i;
    for (i = 0; i < num_entries; i++)
    {
      OVERLAPPED_ENTRY *ove = &ovea[i];
      SOCKWIZ_SOCK *sockobj = (SOCKWIZ_SOCK *)ove->lpCompletionKey;
      DWORD bytes;
      BOOL res;
      DWORD err;

      sockwiz_async_result *r = &async_waiter->cache[i];

      res = GetOverlappedResultEx(NULL, ove->lpOverlapped, &bytes, 0, FALSE);
      err = GetLastError();

      switch (sockobj->type)
      {
      case sockwiz_socket_type_tcp_listener:
      {
        SOCKWIZ_SOCK *listensockobj = sockobj;
        sockobj = listensockobj->listensocket.pending_accept_sockobj;
        listensockobj->listensocket.pending_accept_sockobj = NULL;
        assert(sockobj != NULL);
        struct sockaddr *remote_address =
            listensockobj->listensocket.pending_accept_address;
        listensockobj->listensocket.pending_accept_address = NULL;

        r->sock = get_sockhandle(sockobj);
        r->type = sockwiz_async_accept;

        assert(sockobj->os_socket != INVALID_SOCKET);

        if (res)
        {
          err = update_accept_context(sockobj->os_socket, listensockobj->os_socket);
          if (err != SOCKWIZ_SUCCESS)
          {
            res = FALSE;
          }
        }

        if (res)
        {
          r->failed = 0;
          r->info = 0;
          get_acceptex_remoteaddress(listensockobj, remote_address);
        }
        else
        {
          r->failed = 1;
          r->info = err;
          closesocket(sockobj->os_socket);
          sockobj->os_socket = INVALID_SOCKET;
        }

        break;
      }
      case sockwiz_socket_type_tcp:
      case sockwiz_socket_type_udp:

        r->sock = get_sockhandle(sockobj);

        if (sockobj->connecting)
        {
          assert(sockobj->type == sockwiz_socket_type_tcp);

          r->type = sockwiz_async_connect;

          if (res && (sockobj->os_socket != INVALID_SOCKET))
          {
            err = update_connect_context(sockobj->os_socket);
            if (err != SOCKWIZ_SUCCESS)
            {
              res = FALSE;
            }
          }

          if (res)
          {
            r->failed = 0;
            r->info = 0;
          }
          else
          {
            r->failed = 1;
            r->info = err;

            if (sockobj->os_socket != INVALID_SOCKET)
            {
              closesocket(sockobj->os_socket);
              sockobj->os_socket = INVALID_SOCKET;
            }
          }

          sockobj->connecting = 0;
        }
        else
        {
          r->type =
              ove->lpOverlapped == &sockobj->datasocket.write_ov ? sockwiz_async_write : sockwiz_async_read;

          if (res)
          {
            r->failed = 0;
            r->info = (r->type == sockwiz_async_read ? bytes : 0);
          }
          else
          {
            r->failed = 1;
            r->info = err;
          }
        }

        break;

      default:

        ABORTMSG("Bad socket type", SOCKWIZ_FAILURE);
      }
    }

    async_waiter->cache_count = num_entries;
    rc = SOCKWIZ_SUCCESS;
  }

  return rc;
}

#else // WINBUILD

static int
check_and_request_epoll_event(
    SOCKWIZ_SOCK *sockobj,
    uint32_t inoutmask // EPOLLIN, EPOLLOUT, or both
)
{
  int rc;
  int op;
  struct epoll_event event;

  assert(sockobj->async_waiter != NULL);
  assert(inoutmask != 0);
  assert((inoutmask & ~(EPOLLIN | EPOLLOUT)) == 0);

  event.data.ptr = sockobj;
  event.events = EPOLLET | EPOLLONESHOT | inoutmask;

  if (sockobj->first_epoll_issued == 0)
  {
    op = EPOLL_CTL_ADD;
    sockobj->first_epoll_issued = 1;
  }
  else
  {
    op = EPOLL_CTL_MOD;
  }

  if (epoll_ctl(
          sockobj->async_waiter->epoll_handle,
          op,
          sockobj->os_socket,
          &event) == -1)
  {
    rc = SOCKWIZ_ERROR_ENCODE(errno);
    ERRORMSG((op == EPOLL_CTL_ADD ? "EPOLL_CTL_ADD" : "EPOLL_CTL_MOD"), rc);
  }
  else
  {
    rc = SOCKWIZ_SUCCESS;
  }

  return rc;
}

static inline void
advance_closing_list(
    SOCKWIZ_ASYNC_WAITER *async_waiter)
{
  SOCKWIZ_SOCK *sockobj = async_waiter->closing_head;
  async_waiter->closing_head = sockobj->next;
  if (async_waiter->closing_head == NULL)
  {
    async_waiter->closing_tail = &async_waiter->closing_head;
  }
  else
  {
    sockobj->next = NULL;
  }
}

static int
send_full(
    SOCKWIZ_SOCK *sockobj,
    char *bufptr,
    int wrlen,
    struct sockaddr *remote_address)
{
  int rc;

  assert(sockobj->datasocket.pending_write_buf == NULL);
  assert(sockobj->datasocket.pending_write_buf_len == 0);
  assert(sockobj->datasocket.pending_write_address == NULL);

  for (;;)
  {
    rc = sendto(
        sockobj->os_socket,
        bufptr, wrlen, 0,
        remote_address,
        (remote_address == NULL ? 0 : get_sockaddr_length(sockobj->address_family)));

    if (rc == SOCKET_ERROR)
    {
      int err = WSAGetLastError();
      if (err == EWOULDBLOCK)
      {
        sockobj->datasocket.pending_write_buf = bufptr;
        sockobj->datasocket.pending_write_buf_len = wrlen;
        sockobj->datasocket.pending_write_address = remote_address;

        rc = check_and_request_epoll_event(
            sockobj,
            EPOLLOUT |
                (sockobj->datasocket.pending_read_buf != NULL ? EPOLLIN : 0));
        if (rc == SOCKWIZ_SUCCESS)
        {
          rc = SOCKWIZ_PENDING;
        }
        else
        {
          assert(rc != SOCKWIZ_PENDING);

          sockobj->datasocket.pending_write_buf = NULL;
          sockobj->datasocket.pending_write_buf_len = 0;
          sockobj->datasocket.pending_write_address = NULL;
        }
      }
      else
      {
        rc = SOCKWIZ_ERROR_ENCODE(err);
      }
    }
    else
    {
      if (rc < wrlen)
      {
        bufptr += rc;
        wrlen -= rc;
        continue;
      }
      else
      {
        rc = SOCKWIZ_SUCCESS;
      }
    }

    break;
  }

  return rc;
}

static int
async_waiter_wait_epoll(
    SOCKWIZ_ASYNC_WAITER *async_waiter,
    int timeout)
{
  int rc;
  struct epoll_event epea[ASYNC_RESULT_CACHE_SIZE / 2];
  int num_entries;
  int j = 0;

  assert(async_waiter->cache_count == 0);
  assert(async_waiter->cache_index == 0);

  while (async_waiter->closing_head != NULL && j < ASYNC_RESULT_CACHE_SIZE)
  {
    SOCKWIZ_SOCK *sockobj = async_waiter->closing_head;

    sockwiz_async_result *r = &async_waiter->cache[j++];
    r->failed = 1;
    r->info = SOCKWIZ_CANCELLED;

    switch (sockobj->type)
    {
    case sockwiz_socket_type_tcp_listener:

      assert(sockobj->listensocket.pending_accept_sockobj != NULL);
      r->sock = get_sockhandle(sockobj->listensocket.pending_accept_sockobj);
      r->type = sockwiz_async_accept;
      sockobj->listensocket.pending_accept_sockobj = NULL;
      sockobj->listensocket.pending_accept_address = NULL;
      advance_closing_list(async_waiter);

      break;

    case sockwiz_socket_type_tcp:
    case sockwiz_socket_type_udp:

      r->sock = get_sockhandle(sockobj);

      if (sockobj->connecting)
      {
        r->type = sockwiz_async_connect;
        sockobj->connecting = 0;
        advance_closing_list(async_waiter);
      }
      else
      {
        if (sockobj->datasocket.pending_read_buf != NULL)
        {
          r->type = sockwiz_async_read;
          sockobj->datasocket.pending_read_buf = NULL;
          sockobj->datasocket.pending_read_buf_len = 0;
          sockobj->datasocket.pending_read_address = NULL;

          if (sockobj->datasocket.pending_write_buf == NULL)
          {
            advance_closing_list(async_waiter);
          }
        }
        else if (sockobj->datasocket.pending_write_buf != NULL)
        {
          r->type = sockwiz_async_write;
          sockobj->datasocket.pending_write_buf = NULL;
          sockobj->datasocket.pending_write_buf_len = 0;
          sockobj->datasocket.pending_write_address = NULL;
          advance_closing_list(async_waiter);
        }
        else
        {
          ABORTMSG("Pending operations expected", SOCKWIZ_FAILURE);
        }
      }

      break;

    default:
      ABORTMSG("Bad socket type", SOCKWIZ_FAILURE);
    }
  }

  if (j > 0)
  {
    async_waiter->cache_count = j;
    return SOCKWIZ_SUCCESS;
  }

  num_entries = epoll_wait(
      async_waiter->epoll_handle,
      epea,
      ASYNC_RESULT_CACHE_SIZE / 2,
      timeout);

  if (num_entries == 0)
  {
    rc = SOCKWIZ_TIMEOUT;
  }
  else if (num_entries < 0)
  {
    assert(num_entries == -1);
    ABORTMSG("epoll_wait", errno);
  }
  else
  {
    int i;
    for (i = 0; i < num_entries; i++)
    {
      struct epoll_event *epe = &epea[i];
      SOCKWIZ_SOCK *sockobj = (SOCKWIZ_SOCK *)epe->data.ptr;

      sockwiz_async_result *r;

      switch (sockobj->type)
      {
      case sockwiz_socket_type_tcp_listener:
      {
        SOCKWIZ_SOCK *listensockobj = sockobj;
        sockobj = listensockobj->listensocket.pending_accept_sockobj;

        if (sockobj != NULL)
        {
          listensockobj->listensocket.pending_accept_sockobj = NULL;
          struct sockaddr *remote_address =
              listensockobj->listensocket.pending_accept_address;
          listensockobj->listensocket.pending_accept_address = NULL;

          r = &async_waiter->cache[j++];

          r->sock = get_sockhandle(sockobj);
          r->type = sockwiz_async_accept;

          int ralen = get_sockaddr_length(sockobj->address_family);
          sockobj->os_socket = accept(listensockobj->os_socket, remote_address, &ralen);
          if (sockobj->os_socket == INVALID_SOCKET)
          {
            r->failed = 1;
            r->info = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
          }
          else
          {
            r->failed = 0;
            r->info = 0;
          }
        }

        break;
      }

      case sockwiz_socket_type_tcp:
      case sockwiz_socket_type_udp:

        if (sockobj->connecting)
        {
          assert(sockobj->type == sockwiz_socket_type_tcp);

          r = &async_waiter->cache[j++];

          r->sock = get_sockhandle(sockobj);
          r->type = sockwiz_async_connect;

          int err;
          int optlen = sizeof(err);
          if (getsockopt(sockobj->os_socket, SOL_SOCKET, SO_ERROR, (char *)&err, &optlen) == SOCKET_ERROR)
          {
            err = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
          }

          if (err == SOCKWIZ_SUCCESS)
          {
            r->failed = 0;
            r->info = 0;
          }
          else
          {
            r->failed = 1;
            r->info = err;

            if (sockobj->os_socket != INVALID_SOCKET)
            {
              closesocket(sockobj->os_socket);
              sockobj->os_socket = INVALID_SOCKET;
            }
          }

          sockobj->connecting = 0;
        }
        else
        {
          uint32_t events = epe->events;

          if (sockobj->datasocket.pending_read_buf != NULL &&
              ((events & (EPOLLIN | EPOLLERR | EPOLLHUP)) != 0))
          {
            r = &async_waiter->cache[j++];
            r->sock = get_sockhandle(sockobj);
            r->type = sockwiz_async_read;

            int fromlen = get_sockaddr_length(sockobj->address_family);
            struct sockaddr *ra = sockobj->datasocket.pending_read_address;
            int rc1 = recvfrom(
                sockobj->os_socket,
                sockobj->datasocket.pending_read_buf,
                sockobj->datasocket.pending_read_buf_len, 0,
                ra, (ra == NULL ? NULL : &fromlen));

            if (rc1 == SOCKET_ERROR)
            {
              r->failed = 1;
              r->info = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
            }
            else
            {
              r->failed = 0;
              r->info = rc1;
            }

            sockobj->datasocket.pending_read_buf = NULL;
            sockobj->datasocket.pending_read_buf_len = 0;
            sockobj->datasocket.pending_read_address = NULL;
          }

          if (sockobj->datasocket.pending_write_buf != NULL &&
              ((events & (EPOLLOUT | EPOLLERR)) != 0))
          {
            char *bufptr = sockobj->datasocket.pending_write_buf;
            int wrlen = sockobj->datasocket.pending_write_buf_len;
            struct sockaddr *remote_address = sockobj->datasocket.pending_write_address;

            sockobj->datasocket.pending_write_buf = NULL;
            sockobj->datasocket.pending_write_buf_len = 0;
            sockobj->datasocket.pending_write_address = NULL;

            int rc1 = send_full(sockobj, bufptr, wrlen, remote_address);

            if (rc1 != SOCKWIZ_PENDING)
            {
              r = &async_waiter->cache[j++];
              r->sock = get_sockhandle(sockobj);
              r->type = sockwiz_async_write;

              if (rc1 == SOCKWIZ_SUCCESS)
              {
                r->failed = 0;
                r->info = 0;
              }
              else
              {
                r->failed = 1;
                r->info = rc1;
              }
            }
          }
        }

        break;

      default:

        ABORTMSG("Bad socket type", SOCKWIZ_FAILURE);
      }
    }

    async_waiter->cache_count = j;
    rc = SOCKWIZ_SUCCESS;
  }

  return rc;
}

#endif // !WINBUILD

static int
init_socket_async_waiter(
    SOCKET s,
    void *context,
    SOCKWIZ_ASYNC_WAITER *async_waiter)
{
  int rc;

#ifdef WINBUILD

  if (CreateIoCompletionPort(
          (HANDLE)s, async_waiter->iocp_handle, (ULONG_PTR)context, 0) == NULL)
  {
    rc = SOCKWIZ_ERROR_ENCODE(GetLastError());
    ERRORMSG("CreateIoCompletionPort", rc);
    goto exit;
  }

  if (SetFileCompletionNotificationModes(
          (HANDLE)s,
          FILE_SKIP_COMPLETION_PORT_ON_SUCCESS |
              FILE_SKIP_SET_EVENT_ON_HANDLE) == FALSE)
  {
    rc = SOCKWIZ_ERROR_ENCODE(GetLastError());
    ERRORMSG("SetFileCompletionNotificationModes", rc);
    goto exit;
  }

#else // WINBUILD

  if (set_socket_nonblocking(s) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(errno);
    ERRORMSG("set-nonblocking", rc);
    goto exit;
  }

#endif // !WINBUILD

  rc = SOCKWIZ_SUCCESS;

exit:

  return rc;
}

int sockwiz_async_waiter_wait(
    sockwiz_async_waiter_t async_waiter_handle,
    int timeout,                 // millisec, 0/immediate, -1/infinite
    sockwiz_async_result *result // out
)
{
  int rc;
  SOCKWIZ_ASYNC_WAITER *async_waiter = (SOCKWIZ_ASYNC_WAITER *)async_waiter_handle;

  while (async_waiter->cache_count == 0)
  {
#ifdef WINBUILD

    rc = async_waiter_wait_iocp(async_waiter, timeout);

#else // WINBUILD

    rc = async_waiter_wait_epoll(async_waiter, timeout);

#endif //  !WINBUILD

    if (rc != SOCKWIZ_SUCCESS)
    {
      return rc;
    }
  }

  int i = async_waiter->cache_index;
  const int c = async_waiter->cache_count;
  assert(i >= 0 && i < c);

  *result = async_waiter->cache[i++];
  if (i == c)
  {
    async_waiter->cache_index = 0;
    async_waiter->cache_count = 0;
  }
  else
  {
    async_waiter->cache_index = i;
  }

  return SOCKWIZ_SUCCESS;
}

sockwiz_socket_t
sockwiz_socket_allocate(
    sockwiz_socket_type type,
    int address_family,
    int caller_context_size)
{
  SOCKWIZ_SOCK *sockobj;

  if (caller_context_size > 65536 || caller_context_size < 0)
  {
    goto failexit;
  }

  sockobj = malloc(sizeof(SOCKWIZ_SOCK) + caller_context_size);

  if (sockobj != NULL)
  {
    memset(sockobj, 0, (sizeof(SOCKWIZ_SOCK) + caller_context_size));
    sockobj->type = type;
    sockobj->address_family = address_family;
    sockobj->os_socket = INVALID_SOCKET;
    return get_sockhandle(sockobj);
  }

failexit:

  return NULL;
}

int sockwiz_async_waiter_create(
    sockwiz_async_waiter_t *async_waiter_handle // out
)
{
  SOCKWIZ_ASYNC_WAITER *async_waiter;
  int rc;

  async_waiter = malloc(sizeof(SOCKWIZ_ASYNC_WAITER));
  if (async_waiter == NULL)
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("malloc", rc);
    goto exit;
  }

  memset(async_waiter, 0, sizeof(*async_waiter));

#ifdef WINBUILD

  async_waiter->iocp_handle = CreateIoCompletionPort(INVALID_HANDLE_VALUE, NULL, 0, 1);
  if (async_waiter->iocp_handle == NULL)
  {
    rc = SOCKWIZ_ERROR_ENCODE(GetLastError());
    ERRORMSG("CreateIoCompletionPort", rc);
    goto exit;
  }

#else // WINBUILD

  async_waiter->closing_head = NULL;
  async_waiter->closing_tail = &async_waiter->closing_head;

  async_waiter->epoll_handle = epoll_create1(EPOLL_CLOEXEC);
  if (async_waiter->epoll_handle == -1)
  {
    rc = SOCKWIZ_ERROR_ENCODE(errno);
    ERRORMSG("epoll_create1", rc);
    goto exit;
  }

#endif // !WINBUILD

  *async_waiter_handle = (sockwiz_async_waiter_t)async_waiter;
  async_waiter = NULL;
  rc = SOCKWIZ_SUCCESS;

exit:

  if (async_waiter != NULL)
  {
    async_waiter_close_internal(async_waiter);
  }

  return rc;
}

void sockwiz_async_waiter_close(
    sockwiz_async_waiter_t async_waiter_handle)
{
  SOCKWIZ_ASYNC_WAITER *async_waiter = (SOCKWIZ_ASYNC_WAITER *)async_waiter_handle;
  async_waiter_close_internal(async_waiter);
}

void sockwiz_socket_free(
    sockwiz_socket_t sock)
{
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);

  assert(sockobj->os_socket == INVALID_SOCKET);

  free(sockobj);
}

int sockwiz_socket_set_async_waiter(
    sockwiz_socket_t sock,
    sockwiz_async_waiter_t async_waiter_handle)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);

  assert(sockobj->async_waiter == NULL);

  sockobj->async_waiter = (SOCKWIZ_ASYNC_WAITER *)async_waiter_handle;

  if (sockobj->os_socket != INVALID_SOCKET)
  {
    rc = init_socket_async_waiter(sockobj->os_socket, sockobj, sockobj->async_waiter);
  }
  else
  {
    rc = SOCKWIZ_SUCCESS;
  }

  return rc;
}

int sockwiz_socket_set_buffers(
    sockwiz_socket_t sock,
    int so_sndbuf, // use -1 for no change
    int so_rcvbuf  // use -1 for no change
)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);

  assert(sockobj->os_socket != INVALID_SOCKET);

  if (so_sndbuf != -1)
  {
    if (setsockopt(sockobj->os_socket, SOL_SOCKET, SO_SNDBUF, (const char *)&so_sndbuf, sizeof(so_sndbuf)) == SOCKET_ERROR)
    {
      rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
      ERRORMSG("SO_SNDBUF", rc);
      goto exit;
    }
  }

  if (so_rcvbuf != -1)
  {
    if (setsockopt(sockobj->os_socket, SOL_SOCKET, SO_RCVBUF, (const char *)&so_rcvbuf, sizeof(so_rcvbuf)) == SOCKET_ERROR)
    {
      rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
      ERRORMSG("SO_RCVBUF", rc);
      goto exit;
    }
  }

  rc = SOCKWIZ_SUCCESS;

exit:

  return rc;
}

int sockwiz_socket_get_local_address(
    sockwiz_socket_t sock,
    struct sockaddr *local_address)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);

  assert(sockobj->os_socket != INVALID_SOCKET);

  int addrlen = get_sockaddr_length(sockobj->address_family);

  if (getsockname(sockobj->os_socket, local_address, &addrlen) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("getsockname", rc);
  }
  else
  {
    assert(addrlen == get_sockaddr_length(sockobj->address_family));
    rc = SOCKWIZ_SUCCESS;
  }

  return rc;
}

int sockwiz_tcp_listener_open(
    sockwiz_socket_t sock,
    struct sockaddr *local_address,
    int backlog,
    unsigned int flags)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);
  SOCKET sl = INVALID_SOCKET;

  assert(sockobj->os_socket == INVALID_SOCKET);
  assert(sockobj->type == sockwiz_socket_type_tcp_listener);

  if (sockobj->address_family != local_address->sa_family)
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("address family mismatch", rc);
    goto exit;
  }

  sl = socket(local_address->sa_family, SOCK_STREAM, IPPROTO_TCP);
  if (sl == INVALID_SOCKET)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("socket", rc);
    goto exit;
  }

  if (flags & ~(SOCKWIZ_LISTENER_FLAG_REUSEPORT))
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("bad listener flag", rc);
    goto exit;
  }

  if (flags & SOCKWIZ_LISTENER_FLAG_REUSEPORT)
  {
#ifdef WINBUILD
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("REUSEPORT not supported on Windows yet", rc);
    goto exit;
#else
    int optval = 1;
    if (setsockopt(sl, SOL_SOCKET, SO_REUSEPORT, &optval, sizeof(optval)) == SOCKET_ERROR)
    {
      rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
      ERRORMSG("SO_REUSEPORT", rc);
      goto exit;
    }
#endif
  }

  if (bind(sl, local_address, get_sockaddr_length(sockobj->address_family)) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("bind", rc);
    goto exit;
  }

  if (listen(sl, backlog) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("listen", rc);
    goto exit;
  }

  sockobj->os_socket = sl;
  sl = INVALID_SOCKET;
  rc = SOCKWIZ_SUCCESS;

exit:

  if (sl != INVALID_SOCKET)
  {
    closesocket(sl);
  }

  return rc;
}

void sockwiz_tcp_listener_close(
    sockwiz_socket_t sock)
{
  SOCKWIZ_SOCK *listensockobj = get_sockobj(sock);
  assert(listensockobj->os_socket != INVALID_SOCKET);
  assert(listensockobj->type == sockwiz_socket_type_tcp_listener);

#ifndef WINBUILD

  if (listensockobj->listensocket.pending_accept_sockobj != NULL)
  {
    SOCKWIZ_ASYNC_WAITER *async_waiter = listensockobj->async_waiter;
    assert(async_waiter != NULL);
    assert(listensockobj->next == NULL);

    *async_waiter->closing_tail = listensockobj;
    async_waiter->closing_tail = &listensockobj->next;
  }

#endif // !WINBUILD

  closesocket(listensockobj->os_socket);
  listensockobj->os_socket = INVALID_SOCKET;
}

void optimize_ephemeral_port_usage(
    SOCKET s)
{
  int rc;
  int optval = 0xffffffff;

#ifdef WINBUILD
#ifndef SO_REUSE_UNICASTPORT
#define SO_REUSE_UNICASTPORT 0x3007
#endif
  rc = setsockopt(s, SOL_SOCKET, SO_REUSE_UNICASTPORT, (const char *)&optval, sizeof(optval));
  rc = 0;
#else  // WINBUILD
  rc = setsockopt(s, SOL_IP, IP_BIND_ADDRESS_NO_PORT, (const char *)&optval, sizeof(optval));
#endif // !WINBUILD
  if (rc == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("Failed to optimize ephemeral port usage. CONTINUING...", rc);
  }
}

int sockwiz_tcp_connect(
    sockwiz_socket_t sock,
    struct sockaddr *local_address, // opt
    struct sockaddr *remote_address,
    unsigned int flags)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);
  SOCKET cc = INVALID_SOCKET;
  int address_length;
  struct sockaddr_storage address = {0};

  assert(sockobj->os_socket == INVALID_SOCKET);
  assert(sockobj->type == sockwiz_socket_type_tcp);
  assert((flags & (~(SOCKWIZ_TCP_CONNECT_FLAG_REUSEADDR))) == 0);

  if (sockobj->async_waiter == NULL)
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("async_waiter NULL", rc);
    goto exit;
  }

  if (sockobj->address_family != remote_address->sa_family)
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("address family mismatch", rc);
    goto exit;
  }

  cc = socket(remote_address->sa_family, SOCK_STREAM, IPPROTO_TCP);

  if (cc == INVALID_SOCKET)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("socket", rc);
    goto exit;
  }

  address_length = get_sockaddr_length(sockobj->address_family);

  if (local_address != NULL)
  {
    if (sockobj->address_family != local_address->sa_family)
    {
      rc = SOCKWIZ_FAILURE;
      ERRORMSG("address family mismatch", rc);
      goto exit;
    }
  }
#ifdef WINBUILD
  else
  {
    local_address = (struct sockaddr *)&address;
    local_address->sa_family = remote_address->sa_family;
  }
#endif // WINBUILD

  if (flags & SOCKWIZ_TCP_CONNECT_FLAG_REUSEADDR)
  {
    int optval = 1;
    if (setsockopt(cc, SOL_SOCKET, SO_REUSEADDR, (const char *)&optval, sizeof(optval)) == SOCKET_ERROR)
    {
      rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
      ERRORMSG("SO_REUSEADDR", rc);
      goto exit;
    }
  }

  if (local_address != NULL)
  {
    if (local_address->sa_family == AF_INET || local_address->sa_family == AF_INET6)
    {
      if (((struct sockaddr_in *)local_address)->sin_port == 0)
      {
        optimize_ephemeral_port_usage(cc);
      }
    }

    if (bind(cc, local_address, address_length) == SOCKET_ERROR)
    {
      rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
      ERRORMSG("bind", rc);
      goto exit;
    }
  }

  rc = init_socket_async_waiter(cc, sockobj, sockobj->async_waiter);
  if (rc != SOCKWIZ_SUCCESS)
  {
    goto exit;
  }

  if (sockobj->connecting)
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("illegal async request", rc);
    goto exit;
  }

#ifdef WINBUILD

  get_connectex_fn();

  DWORD bytes;
  BOOL res = fn_connect_ex(
      cc,
      remote_address,
      address_length,
      NULL,
      0,
      &bytes,
      &sockobj->datasocket.write_ov);

  if (res == FALSE)
  {
    rc = WSAGetLastError();
    if (rc != ERROR_IO_PENDING)
    {
      rc = SOCKWIZ_ERROR_ENCODE(rc);
      ERRORMSG("ConnectEx", rc);
      goto exit;
    }

    sockobj->connecting = 1;
    sockobj->os_socket = cc;
    cc = INVALID_SOCKET;
    rc = SOCKWIZ_PENDING;
  }
  else
  {
    rc = update_connect_context(cc);
    if (rc != SOCKWIZ_SUCCESS)
    {
      goto exit;
    }

    sockobj->os_socket = cc;
    cc = INVALID_SOCKET;
    rc = SOCKWIZ_SUCCESS;
  }

#else // WINBUILD

  if (connect(cc, remote_address, address_length) == SOCKET_ERROR)
  {
    rc = WSAGetLastError();
    if (rc != EINPROGRESS)
    {
      rc = SOCKWIZ_ERROR_ENCODE(rc);
      if (rc != 99)
        ERRORMSG("connect", rc);
      goto exit;
    }

    sockobj->connecting = 1;
    sockobj->os_socket = cc;
    cc = INVALID_SOCKET;

    rc = check_and_request_epoll_event(sockobj, EPOLLOUT);
    if (rc == SOCKWIZ_SUCCESS)
    {
      rc = SOCKWIZ_PENDING;
    }
    else
    {
      assert(rc != SOCKWIZ_PENDING);

      sockobj->connecting = 0;
      cc = sockobj->os_socket;
      sockobj->os_socket = INVALID_SOCKET;
    }
  }
  else
  {
    sockobj->os_socket = cc;
    cc = INVALID_SOCKET;
    rc = SOCKWIZ_SUCCESS;
  }

#endif // !WINBUILD

exit:

  if (cc != INVALID_SOCKET)
  {
    closesocket(cc);
  }

  return rc;
}

int sockwiz_tcp_accept(
    sockwiz_socket_t listener_sock,
    sockwiz_socket_t sock,
    struct sockaddr *remote_address // opt out
)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);
  SOCKWIZ_SOCK *listensockobj = get_sockobj(listener_sock);
  SOCKET cc = INVALID_SOCKET;
  int address_length;

  assert(listensockobj->os_socket != INVALID_SOCKET);
  assert(listensockobj->type == sockwiz_socket_type_tcp_listener);

  assert(sockobj->os_socket == INVALID_SOCKET);
  assert(sockobj->type == sockwiz_socket_type_tcp);

  if (listensockobj->async_waiter == NULL)
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("async_waiter NULL", rc);
    goto exit;
  }

  if (listensockobj->address_family != sockobj->address_family)
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("address family mismatch", rc);
    goto exit;
  }

  address_length = get_sockaddr_length(sockobj->address_family);

  if (listensockobj->listensocket.pending_accept_sockobj != NULL)
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("illegal async request", rc);
    goto exit;
  }

#ifdef WINBUILD

  cc = socket(sockobj->address_family, SOCK_STREAM, IPPROTO_TCP);

  if (cc == INVALID_SOCKET)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("socket", rc);
    goto exit;
  }

  get_acceptex_fn();

  DWORD bytes;
  BOOL res = fn_accept_ex(
      listensockobj->os_socket,
      cc,
      listensockobj->listensocket.address_buffer,
      0,
      0,
      sizeof(listensockobj->listensocket.address_buffer),
      &bytes,
      &listensockobj->listensocket.accept_ov);

  if (res == FALSE)
  {
    rc = WSAGetLastError();
    if (rc != ERROR_IO_PENDING)
    {
      rc = SOCKWIZ_ERROR_ENCODE(rc);
      ERRORMSG("AcceptEx", rc);
      goto exit;
    }

    listensockobj->listensocket.pending_accept_sockobj = sockobj;
    listensockobj->listensocket.pending_accept_address = remote_address;
    sockobj->os_socket = cc;
    cc = INVALID_SOCKET;
    rc = SOCKWIZ_PENDING;
  }
  else
  {
    rc = update_accept_context(cc, listensockobj->os_socket);
    if (rc != SOCKWIZ_SUCCESS)
    {
      goto exit;
    }

    sockobj->os_socket = cc;
    cc = INVALID_SOCKET;
    rc = SOCKWIZ_SUCCESS;
    get_acceptex_remoteaddress(listensockobj, remote_address);
  }

#else // WINBUILD

  int ralen = address_length;
  cc = accept(listensockobj->os_socket, remote_address, &ralen);
  if (cc == INVALID_SOCKET)
  {
    rc = WSAGetLastError();
    if (rc != EWOULDBLOCK)
    {
      rc = SOCKWIZ_ERROR_ENCODE(rc);
      ERRORMSG("accept", rc);
      goto exit;
    }

    listensockobj->listensocket.pending_accept_sockobj = sockobj;
    listensockobj->listensocket.pending_accept_address = remote_address;

    rc = check_and_request_epoll_event(listensockobj, EPOLLIN);
    if (rc == SOCKWIZ_SUCCESS)
    {
      rc = SOCKWIZ_PENDING;
    }
    else
    {
      assert(rc != SOCKWIZ_PENDING);

      listensockobj->listensocket.pending_accept_sockobj = NULL;
      listensockobj->listensocket.pending_accept_address = NULL;
    }
  }
  else
  {
    sockobj->os_socket = cc;
    cc = INVALID_SOCKET;
    rc = SOCKWIZ_SUCCESS;
  }

#endif // !WINBUILD

exit:

  if (cc != INVALID_SOCKET)
  {
    closesocket(cc);
  }

  return rc;
}

int sockwiz_tcp_disconnect(
    sockwiz_socket_t sock)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);

  assert(sockobj->os_socket != INVALID_SOCKET);
  assert(sockobj->type == sockwiz_socket_type_tcp);

#ifdef WINBUILD

  get_disconnectex_fn();

  if (fn_disconnect_ex(sockobj->os_socket, NULL, 0, 0) == FALSE)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    // ERRORMSG("DisconnectEx", rc);
    goto exit;
  }

#else // WINBUILD

  if (shutdown(sockobj->os_socket, SHUT_WR) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    // ERRORMSG("shutdown", rc);
    goto exit;
  }

#endif // !WINBUILD

  rc = SOCKWIZ_SUCCESS;

exit:

  return rc;
}

int sockwiz_tcp_get_info(
    sockwiz_socket_t sock,
    unsigned int *rtt,
    unsigned int *synRetrans)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);

  assert(sockobj->os_socket != INVALID_SOCKET);
  assert(sockobj->type == sockwiz_socket_type_tcp);

#ifdef WINBUILD

#ifndef SIO_TCP_INFO
// TODO: Pick up a recent Windows SDK that contains these new APIs.
#define SIO_TCP_INFO _WSAIORW(IOC_VENDOR, 39)
  typedef enum _TCPSTATE
  {
    TCPSTATE_CLOSED,
    TCPSTATE_LISTEN,
    TCPSTATE_SYN_SENT,
    TCPSTATE_SYN_RCVD,
    TCPSTATE_ESTABLISHED,
    TCPSTATE_FIN_WAIT_1,
    TCPSTATE_FIN_WAIT_2,
    TCPSTATE_CLOSE_WAIT,
    TCPSTATE_CLOSING,
    TCPSTATE_LAST_ACK,
    TCPSTATE_TIME_WAIT,
    TCPSTATE_MAX
  } TCPSTATE;
  typedef struct _TCP_INFO_v0
  {
    TCPSTATE State;
    ULONG Mss;
    ULONG64 ConnectionTimeMs;
    BOOLEAN TimestampsEnabled;
    ULONG RttUs;
    ULONG MinRttUs;
    ULONG BytesInFlight;
    ULONG Cwnd;
    ULONG SndWnd;
    ULONG RcvWnd;
    ULONG RcvBuf;
    ULONG64 BytesOut;
    ULONG64 BytesIn;
    ULONG BytesReordered;
    ULONG BytesRetrans;
    ULONG FastRetrans;
    ULONG DupAcksIn;
    ULONG TimeoutEpisodes;
    UCHAR SynRetrans;
  } TCP_INFO_v0, *PTCP_INFO_v0;
#endif

  TCP_INFO_v0 info;
  DWORD ver = 0;
  DWORD bytes;

  if (WSAIoctl(sockobj->os_socket, SIO_TCP_INFO, &ver, sizeof(ver), &info, sizeof(info), &bytes, NULL, NULL) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("WSAIoctl SIO_TCP_INFO", rc);
    goto exit;
  }

  *rtt = info.RttUs;
  *synRetrans = info.SynRetrans;

#else // WINBUILD

  struct tcp_info info;
  socklen_t tcp_info_len = sizeof(info);

  if (getsockopt(sockobj->os_socket, IPPROTO_TCP, TCP_INFO, (void *)&info, &tcp_info_len) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("getsockopt TCP_INFO", rc);
    goto exit;
  }

  *rtt = info.tcpi_rtt;
  *synRetrans = info.tcpi_total_retrans;

#endif // !WINBUILD

  rc = SOCKWIZ_SUCCESS;

exit:

  return rc;
}

int sockwiz_tcp_set_keepalive(
    sockwiz_socket_t sock,
    int keepalive_sec)
{
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);
  assert(sockobj->os_socket != INVALID_SOCKET);
  assert(sockobj->type == sockwiz_socket_type_tcp);

  int rc;

#ifdef WINBUILD

  DWORD bytes;
  struct tcp_keepalive tka = {0};
  tka.onoff = 1;
  tka.keepalivetime = keepalive_sec * 1000;
  tka.keepaliveinterval = 1 * 1000; // 1 sec

  if (WSAIoctl(sockobj->os_socket, SIO_KEEPALIVE_VALS, &tka, sizeof(tka), NULL, 0, &bytes, NULL, NULL) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("WSAIoctl SIO_KEEPALIVE_VALS", rc);
    goto exit;
  }

#else // WINBUILD

  int optval;

  optval = 1;
  if (setsockopt(sockobj->os_socket, SOL_SOCKET, SO_KEEPALIVE, (const char *)&optval, sizeof(optval)) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("setsockopt SO_KEEPALIVE", rc);
    goto exit;
  }

  optval = keepalive_sec;
  if (setsockopt(sockobj->os_socket, SOL_TCP, TCP_KEEPIDLE, (void *)&optval, sizeof(optval)) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("setsockopt TCP_KEEPIDLE", rc);
    goto exit;
  }

  optval = 10;
  if (setsockopt(sockobj->os_socket, SOL_TCP, TCP_KEEPCNT, (void *)&optval, sizeof(optval)) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("setsockopt TCP_KEEPCNT", rc);
    goto exit;
  }

  optval = 1;
  if (setsockopt(sockobj->os_socket, SOL_TCP, TCP_KEEPINTVL, (void *)&optval, sizeof(optval)) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("setsockopt TCP_KEEPINTVL", rc);
    goto exit;
  }

#endif // !WINBUILD

  rc = SOCKWIZ_SUCCESS;

exit:

  return rc;
}

void sockwiz_tcp_close(
    sockwiz_socket_t sock,
    unsigned int flags)
{
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);
  assert(sockobj->os_socket != INVALID_SOCKET);
  assert(sockobj->type == sockwiz_socket_type_tcp);
  assert((flags & (~(SOCKWIZ_TCP_CLOSE_ABORTIVE))) == 0);

#ifndef WINBUILD

  if (sockobj->connecting ||
      sockobj->datasocket.pending_read_buf != NULL ||
      sockobj->datasocket.pending_write_buf != NULL)
  {
    SOCKWIZ_ASYNC_WAITER *async_waiter = sockobj->async_waiter;
    assert(async_waiter != NULL);
    assert(sockobj->next == NULL);

    *async_waiter->closing_tail = sockobj;
    async_waiter->closing_tail = &sockobj->next;
  }

#endif // !WINBUILD

  if (flags & SOCKWIZ_TCP_CLOSE_ABORTIVE)
  {
    struct linger lingeron = {0};
    lingeron.l_onoff = 1;
    setsockopt(sockobj->os_socket, SOL_SOCKET, SO_LINGER, (char *)&lingeron, sizeof(lingeron));
  }

  closesocket(sockobj->os_socket);
  sockobj->os_socket = INVALID_SOCKET;
}

int sockwiz_udp_open(
    sockwiz_socket_t sock,
    struct sockaddr *local_address,
    struct sockaddr *remote_address // opt
)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);
  SOCKET uu = INVALID_SOCKET;

  assert(sockobj->os_socket == INVALID_SOCKET);
  assert(sockobj->type == sockwiz_socket_type_udp);

  if (sockobj->address_family != local_address->sa_family)
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("address family mismatch", rc);
    goto exit;
  }

  uu = socket(local_address->sa_family, SOCK_DGRAM, IPPROTO_UDP);
  if (uu == INVALID_SOCKET)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("socket", rc);
    goto exit;
  }

  if (bind(uu, local_address, get_sockaddr_length(sockobj->address_family)) == SOCKET_ERROR)
  {
    rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
    ERRORMSG("bind", rc);
    goto exit;
  }

  if (remote_address != NULL)
  {
    if (sockobj->address_family != remote_address->sa_family)
    {
      rc = SOCKWIZ_FAILURE;
      ERRORMSG("address family mismatch", rc);
      goto exit;
    }

    if (connect(uu, remote_address, get_sockaddr_length(sockobj->address_family)) == SOCKET_ERROR)
    {
      rc = SOCKWIZ_ERROR_ENCODE(WSAGetLastError());
      ERRORMSG("connect", rc);
      goto exit;
    }
  }

  sockobj->os_socket = uu;
  uu = INVALID_SOCKET;
  rc = SOCKWIZ_SUCCESS;

exit:

  if (uu != INVALID_SOCKET)
  {
    closesocket(uu);
  }

  return rc;
}

void sockwiz_udp_close(
    sockwiz_socket_t sock)
{
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);
  assert(sockobj->os_socket != INVALID_SOCKET);
  assert(sockobj->type == sockwiz_socket_type_udp);

#ifndef WINBUILD
  if (sockobj->datasocket.pending_read_buf != NULL ||
      sockobj->datasocket.pending_write_buf != NULL)
  {
    SOCKWIZ_ASYNC_WAITER *async_waiter = sockobj->async_waiter;
    assert(async_waiter != NULL);
    assert(sockobj->next == NULL);

    *async_waiter->closing_tail = sockobj;
    async_waiter->closing_tail = &sockobj->next;
  }
#endif // !WINBUILD

  closesocket(sockobj->os_socket);
  sockobj->os_socket = INVALID_SOCKET;
}

int sockwiz_read(
    sockwiz_socket_t sock,
    char *buf,
    int *len,
    struct sockaddr *remote_address // opt out
)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);

  assert(sockobj->os_socket != INVALID_SOCKET);
  assert(sockobj->type != sockwiz_socket_type_tcp_listener);

#ifdef WINBUILD

  WSABUF wb;
  DWORD bytes;
  DWORD flags = 0;

  wb.len = *len;
  wb.buf = buf;

  if (remote_address != NULL)
  {
    int fromlen = get_sockaddr_length(sockobj->address_family);
    rc = WSARecvFrom(
        sockobj->os_socket,
        &wb, 1, &bytes, &flags,
        remote_address, &fromlen,
        &sockobj->datasocket.read_ov, NULL);
  }
  else
  {
    rc = WSARecv(
        sockobj->os_socket,
        &wb, 1, &bytes, &flags,
        &sockobj->datasocket.read_ov, NULL);
  }

  if (rc == SOCKET_ERROR)
  {
    DWORD err = WSAGetLastError();
    if (err == WSA_IO_PENDING)
    {
      rc = SOCKWIZ_PENDING;
    }
    else
    {
      rc = SOCKWIZ_ERROR_ENCODE(err);
    }
  }
  else
  {
    *len = bytes;
    rc = SOCKWIZ_SUCCESS;
  }

#else // WINBUILD

  int fromlen = get_sockaddr_length(sockobj->address_family);
  rc = recvfrom(
      sockobj->os_socket,
      buf, *len, 0,
      remote_address,
      (remote_address == NULL ? NULL : &fromlen));

  if (rc == SOCKET_ERROR)
  {
    int err = WSAGetLastError();
    if (err == EWOULDBLOCK)
    {
      sockobj->datasocket.pending_read_buf = buf;
      sockobj->datasocket.pending_read_buf_len = *len;
      sockobj->datasocket.pending_read_address = remote_address;

      rc = check_and_request_epoll_event(
          sockobj,
          EPOLLIN |
              (sockobj->datasocket.pending_write_buf != NULL ? EPOLLOUT : 0));
      if (rc == SOCKWIZ_SUCCESS)
      {
        rc = SOCKWIZ_PENDING;
      }
      else
      {
        assert(rc != SOCKWIZ_PENDING);

        sockobj->datasocket.pending_read_buf = NULL;
        sockobj->datasocket.pending_read_buf_len = 0;
        sockobj->datasocket.pending_read_address = NULL;
      }
    }
    else
    {
      rc = SOCKWIZ_ERROR_ENCODE(err);
    }
  }
  else
  {
    *len = rc;
    rc = SOCKWIZ_SUCCESS;
  }

#endif // IWINUBILD

  return rc;
}

int sockwiz_write(
    sockwiz_socket_t sock,
    char *buf,
    int len,
    struct sockaddr *remote_address // opt
)
{
  int rc;
  SOCKWIZ_SOCK *sockobj = get_sockobj(sock);

  assert(sockobj->os_socket != INVALID_SOCKET);
  assert(sockobj->type != sockwiz_socket_type_tcp_listener);

#ifdef WINBUILD

  WSABUF wb;
  DWORD bytes;

  wb.len = len;
  wb.buf = buf;

  if (remote_address != NULL)
  {
    rc = WSASendTo(
        sockobj->os_socket,
        &wb, 1, &bytes, 0,
        remote_address, get_sockaddr_length(sockobj->address_family),
        &sockobj->datasocket.write_ov, NULL);
  }
  else
  {
    rc = WSASend(
        sockobj->os_socket,
        &wb, 1, &bytes, 0,
        &sockobj->datasocket.write_ov, NULL);
  }

  if (rc == SOCKET_ERROR)
  {
    DWORD err = WSAGetLastError();
    if (err == WSA_IO_PENDING)
    {
      rc = SOCKWIZ_PENDING;
    }
    else
    {
      rc = SOCKWIZ_ERROR_ENCODE(err);
    }
  }
  else
  {
    if (len != (int)bytes)
    {
      ABORTMSG("partial send", bytes);
    }
    rc = SOCKWIZ_SUCCESS;
  }

#else // WINBUILD

  rc = send_full(sockobj, buf, len, remote_address);

#endif // !WINBUILD

  return rc;
}

//
// Utility functions
//

typedef struct _UTILSW_THREAD
{

#ifdef WINBUILD
  HANDLE thread_handle;
#else  // WINBUILD
  pthread_t thread_handle;
#endif // !WINBUILD

  utilsw_thread_fn_t utilsw_thread_fn;
  void *context;

} UTILSW_THREAD;

#ifdef WINBUILD
DWORD
#else  // WINBUILD
void *
#endif // !WINBUILD
utilsw_thread_routine(
    void *params)
{
  UTILSW_THREAD *utilsw_thread = (UTILSW_THREAD *)params;

  utilsw_thread->utilsw_thread_fn(utilsw_thread->context);

  return 0;
}

int utilsw_thread_start(
    utilsw_thread_fn_t utilsw_thread_fn,
    void *context,
    utilsw_thread_t *utilsw_thread_handle)
{
  int rc;
  UTILSW_THREAD *utilsw_thread = NULL;

  utilsw_thread = malloc(sizeof(*utilsw_thread));
  if (utilsw_thread == NULL)
  {
    rc = SOCKWIZ_FAILURE;
    ERRORMSG("malloc", rc);
    goto exit;
  }

  memset(utilsw_thread, 0, sizeof(*utilsw_thread));
  utilsw_thread->context = context;
  utilsw_thread->utilsw_thread_fn = utilsw_thread_fn;

#ifdef WINBUILD

  utilsw_thread->thread_handle =
      CreateThread(NULL, 0, &utilsw_thread_routine, (void *)utilsw_thread, 0, NULL);

  if (utilsw_thread->thread_handle == NULL)
  {
    rc = SOCKWIZ_ERROR_ENCODE(GetLastError());
    ERRORMSG("CreateThread", rc);
    goto exit;
  }

#else // WINBUILD

  rc = pthread_create(
      &utilsw_thread->thread_handle, NULL,
      &utilsw_thread_routine, (void *)utilsw_thread);

  if (rc != SOCKWIZ_SUCCESS)
  {
    ERRORMSG("pthread_create", rc);
    goto exit;
  }

#endif // !WINBUILD

  *utilsw_thread_handle = (utilsw_thread_t)utilsw_thread;
  utilsw_thread = NULL;
  rc = SOCKWIZ_SUCCESS;

exit:

  if (utilsw_thread != NULL)
  {
    free(utilsw_thread);
  }

  return rc;
}

void utilsw_thread_stop(
    utilsw_thread_t utilsw_thread_handle)
{
  UTILSW_THREAD *utilsw_thread = (UTILSW_THREAD *)utilsw_thread_handle;

#ifdef WINBUILD

  DWORD rc = WaitForSingleObject(utilsw_thread->thread_handle, INFINITE);
  if (rc != WAIT_OBJECT_0)
  {
    ABORTMSG("WaitForSingleObject", rc)
  }

#else // WINBUILD

  int rc = pthread_join(utilsw_thread->thread_handle, NULL);
  if (rc != 0)
  {
    ABORTMSG("pthread_join", rc)
  }

#endif // !WINBUILD

  free(utilsw_thread);
}

void utilsw_sleep(
    int millisec)
{
#ifdef WINBUILD
  Sleep(millisec);
#else  // WINBUILD
  usleep(millisec * 1000);
#endif // !WINBUILD
}

unsigned long long
utilsw_get_millisec()
{
#ifdef WINBUILD

  return (unsigned long long)GetTickCount64();

#else // WINBUILD

  struct timespec ts;

  if (clock_gettime(CLOCK_MONOTONIC, &ts) != -1)
  {
    return ((unsigned long long)ts.tv_sec * 1000) +
           ((unsigned long long)ts.tv_nsec / 1000000);
  }
  else
  {
    return (unsigned long long)0;
  }

#endif // !WINBUILD
}

#ifdef WINBUILD
static LARGE_INTEGER freq = {0};
#endif // WINBUILD

unsigned long long
utilsw_get_microsec()
{
#ifdef WINBUILD

  LARGE_INTEGER t;

  if (freq.QuadPart == 0)
  {
    if (QueryPerformanceFrequency(&freq) == FALSE || freq.QuadPart == 0)
    {
      return (unsigned long long)0;
    }
  }

  if (QueryPerformanceCounter(&t) == FALSE)
  {
    return (unsigned long long)0;
  }

  return (unsigned long long)(t.QuadPart * 1000000 / freq.QuadPart);

#else // WINBUILD

  struct timespec ts;

  if (clock_gettime(CLOCK_MONOTONIC, &ts) != -1)
  {
    return ((unsigned long long)ts.tv_sec * 1000000) +
           ((unsigned long long)ts.tv_nsec / 1000);
  }
  else
  {
    return (unsigned long long)0;
  }

#endif // !WINBUILD
}

int utilsw_set_affinity(
    int proc_index)
{
  int rc;

#ifdef WINBUILD

  DWORD_PTR affinity = 1;
  if (SetThreadAffinityMask(GetCurrentThread(), affinity << proc_index) == FALSE)
  {
    rc = SOCKWIZ_ERROR_ENCODE(GetLastError());
    ERRORMSG("SetProcessAffinityMask", rc);
    goto exit;
  }

#else // WINBUILD

  cpu_set_t cs;
  CPU_ZERO(&cs);
  CPU_SET(proc_index, &cs);
  if (pthread_setaffinity_np(pthread_self(), sizeof(cs), &cs) != 0)
  {
    rc = SOCKWIZ_ERROR_ENCODE(errno);
    ERRORMSG("pthread_setaffinity_np", rc);
    goto exit;
  }

#endif // !WINBUILD

  rc = SOCKWIZ_SUCCESS;

exit:

  return rc;
}

void utilsw_set_output_stream(
    FILE *output_stream)
{
  sockwiz_output_stream = output_stream;
}

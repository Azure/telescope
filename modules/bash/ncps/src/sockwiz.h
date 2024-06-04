/*++
    Sockwiz is a multi-platform sockets library which provides a simplified
    I/O model.
--*/

#ifdef WINBUILD
#include <winsock2.h>
#else
#include <sys/socket.h>
#include <netinet/tcp.h>
#endif

#define DECLARE_OPAQUE_TYPE(name) \
  struct name##__                 \
  {                               \
    int unused;                   \
  };                              \
  typedef struct name##__ *name

DECLARE_OPAQUE_TYPE(sockwiz_async_waiter_t);
DECLARE_OPAQUE_TYPE(sockwiz_socket_t);

#define SOCKWIZ_SUCCESS 0
#define SOCKWIZ_FAILURE (-1)
#define SOCKWIZ_PENDING (-2)
#define SOCKWIZ_TIMEOUT (-3)
#define SOCKWIZ_CANCELLED (-4)

typedef enum
{
  sockwiz_socket_type_tcp_listener,
  sockwiz_socket_type_tcp,
  sockwiz_socket_type_udp,
} sockwiz_socket_type;

typedef enum
{
  sockwiz_async_read = 0,
  sockwiz_async_write = 1,
  sockwiz_async_accept = 2,
  sockwiz_async_connect = 3,
} sockwiz_async_result_type;

typedef struct _sockwiz_async_result
{
  sockwiz_socket_t sock;
  u_int type : 3;   // sockwiz_async_result_type
  u_int failed : 1; // 0 - success, 1 - failure
  u_int unused : 28;
  //
  // If failed != 0, info contains the specific error code.
  // Otherwise, info contains the number of bytes received
  // for receive operations, and 0 for other operations.
  //
  int info;
} sockwiz_async_result;

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int sockwiz_async_waiter_create(
    sockwiz_async_waiter_t *async_waiter_handle // out
);

// SOCKWIZ_SUCCESS - Success
// SOCKWIZ_TIMEOUT - Timeout
// Otherwise - Failure code
int sockwiz_async_waiter_wait(
    sockwiz_async_waiter_t async_waiter_handle,
    int timeout,                 // millisec, 0/immediate, -1/infinite
    sockwiz_async_result *result // out
);

//
// Caller is responsible for closing an async_waiter only after
// all pending results are drained and no new requests can be
// issued over sockets associated with the async_waiter.
//
void sockwiz_async_waiter_close(
    sockwiz_async_waiter_t async_waiter_handle);

//
// The return value of sockwiz_socket_allocate serves 2 purposes:
// 1. a handle that identifies the socket object to the sockwiz library
// 2. a pointer to a memory blob of caller_context_size which the caller
//    can use for its own purposes. This blob is zeroed out by the lib.
// NULL is returned upon failure.
//
// CONCURRENCY RESPONSIBILITIES FOR THE CLIENT OF THIS LIBRARY:
//
// 1. All API calls related to a given socket object must be invoked in
//    serial fashion for that socket object. Any API call that takes a
//    socket object as input and any API call on the async_waiter
//    associated with a socket object are related to that socket object.
//    As a key example, calling the "close" API on a given socket is
//    illegal when sockwiz_async_waiter_wait is in progress on the
//    async_waiter associated with that socket.
//
// 2. Client can invoke the "close" API on a given socket object while
//    there are pending operations (i.e., calls which have returned
//    SOCKWIZ_PENDING) on the socket. However, client must ensure that
//    all pending operations on the socket are completed before calling
//    sockwiz_socket_free on the socket object.
//
// 3. Only one pending accept operation is legal on a listening socket.
//    Only one pending read operation is legal on a tcp/udp socket.
//    Only one pending write operation is legal on a tcp/udp socket.
//    (A read and a write operation can both be pending on a given socket.)
//
sockwiz_socket_t
sockwiz_socket_allocate(
    sockwiz_socket_type type,
    int address_family,
    int caller_context_size);

void sockwiz_socket_free(
    sockwiz_socket_t sock);

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int sockwiz_socket_set_async_waiter(
    sockwiz_socket_t sock,
    sockwiz_async_waiter_t async_waiter_handle);

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int sockwiz_socket_set_buffers(
    sockwiz_socket_t sock, // must be an opened or connected socket
    int so_sndbuf,         // use -1 for no change
    int so_rcvbuf          // use -1 for no change
);

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int sockwiz_socket_get_local_address(
    sockwiz_socket_t sock,
    struct sockaddr *local_address // out
);

#define SOCKWIZ_LISTENER_FLAG_REUSEPORT 1

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int sockwiz_tcp_listener_open(
    sockwiz_socket_t sock,
    struct sockaddr *local_address,
    int backlog,
    unsigned int flags);

void sockwiz_tcp_listener_close(
    sockwiz_socket_t sock);

#define SOCKWIZ_TCP_CONNECT_FLAG_REUSEADDR 1

// SOCKWIZ_SUCCESS - Success
// SOCKWIZ_PENDING - Pending
// Otherwise - Failure code
int sockwiz_tcp_connect(
    sockwiz_socket_t sock,
    struct sockaddr *local_address, // opt
    struct sockaddr *remote_address,
    unsigned int flags);

// SOCKWIZ_SUCCESS - Success
// SOCKWIZ_PENDING - Pending
// Otherwise - Failure code
int sockwiz_tcp_accept(
    sockwiz_socket_t listener_sock,
    sockwiz_socket_t sock,
    struct sockaddr *remote_address // opt out
);

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int sockwiz_tcp_disconnect( // graceful disconnect (shutdown(SD_SEND))
    sockwiz_socket_t sock);

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int sockwiz_tcp_get_info(
    sockwiz_socket_t sock,
    unsigned int *rtt,
    unsigned int *synRetrans);

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int sockwiz_tcp_set_keepalive(
    sockwiz_socket_t sock,
    int keepalive_sec);

#define SOCKWIZ_TCP_CLOSE_ABORTIVE 1

void sockwiz_tcp_close(
    sockwiz_socket_t sock,
    unsigned int flags);

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int sockwiz_udp_open(
    sockwiz_socket_t sock,
    struct sockaddr *local_address,
    struct sockaddr *remote_address // opt
);

void sockwiz_udp_close(
    sockwiz_socket_t sock);

// SOCKWIZ_SUCCESS - Success
// SOCKWIZ_PENDING - Pending
// Otherwise - Failure code
int sockwiz_read(
    sockwiz_socket_t sock,
    char *buf,
    int *len,                       // inout
    struct sockaddr *remote_address // opt out
);

// SOCKWIZ_SUCCESS - Success
// SOCKWIZ_PENDING - Pending
// Otherwise - Failure code
int sockwiz_write(
    sockwiz_socket_t sock,
    char *buf,
    int len,                        // either writes all "len" bytes or fails
    struct sockaddr *remote_address // opt
);

//
// Utility functions
//

DECLARE_OPAQUE_TYPE(utilsw_thread_t);

typedef void (*utilsw_thread_fn_t)(
    void *context);

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int utilsw_thread_start(
    utilsw_thread_fn_t utilsw_thread_fn,
    void *context,
    utilsw_thread_t *utilsw_thread_handle);

void utilsw_thread_stop(
    utilsw_thread_t utilsw_thread_handle);

void utilsw_sleep(
    int millisec);

unsigned long long
utilsw_get_millisec();

unsigned long long
utilsw_get_microsec();

// SOCKWIZ_SUCCESS - Success
// Otherwise - Failure code
int utilsw_set_affinity(
    int proc_index);

void utilsw_set_output_stream(
    FILE *output_stream);

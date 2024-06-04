#ifdef WINBUILD
#include <winsock2.h>
#include <ws2ipdef.h>
#else //  WINBUILD
#include <unistd.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <errno.h>
#include <signal.h>
#include <ctype.h>

#ifndef min
#define min(a, b) (((a) < (b)) ? (a) : (b))
#endif

#ifndef max
#define max(a, b) (((a) > (b)) ? (a) : (b))
#endif

#endif // !WINBUILD

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sockwiz.h"

// TODO: integrate with build/release system
#define NCPS_MAJOR_VERSION 1
#define NCPS_MINOR_VERSION 1

FILE *cps_output_stream = NULL;

//
// Doubly linked list functions
//

typedef struct _utilsw_list_entry
{
  struct _utilsw_list_entry *next;
  struct _utilsw_list_entry *prev;
} utilsw_list_entry;

static void
utilsw_list_init(
    utilsw_list_entry *head)
{
  head->next = head->prev = head;
}

static int
utilsw_list_is_empty(
    utilsw_list_entry *head)
{
  return (head->next == head) ? 1 : 0;
}

static void
utilsw_list_insert_before(
    utilsw_list_entry *existing_entry,
    utilsw_list_entry *new_entry)
{
  new_entry->next = existing_entry;
  new_entry->prev = existing_entry->prev;
  existing_entry->prev->next = new_entry;
  existing_entry->prev = new_entry;
}

static void
utilsw_list_remove_entry(
    utilsw_list_entry *entry)
{
  entry->next->prev = entry->prev;
  entry->prev->next = entry->next;
}

#define BAIL_IF(cond, code)                                                                           \
  {                                                                                                   \
    if (cond)                                                                                         \
    {                                                                                                 \
      fprintf(cps_output_stream, "FAILURE %d at %s:%d %s\n", code, __FILE__, __LINE__, __FUNCTION__); \
      goto exit;                                                                                      \
    }                                                                                                 \
  }

#define BAILMSG_IF(cond, msg)                                                               \
  {                                                                                         \
    if (cond)                                                                               \
    {                                                                                       \
      fprintf(cps_output_stream, "%s (%s:%d %s)\n", msg, __FILE__, __LINE__, __FUNCTION__); \
      goto exit;                                                                            \
    }                                                                                       \
  }

__inline void
set_locked(volatile long *var, long val)
{
#ifdef WINBUILD
  InterlockedExchange(var, val);
#else
  __sync_add_and_fetch(var, val - (*var));
#endif
}

typedef enum
{
  socket_action_none = 0,
  socket_action_accept,
  socket_action_accept_complete,
  socket_action_connect,
  socket_action_connect_complete,
  socket_action_read,
  socket_action_read_complete,
  socket_action_write,
  socket_action_write_complete,
  socket_action_close,
} socket_action;

typedef struct _cps_socket
{
  utilsw_list_entry link;
  socket_action action;
  int completion_status;
  int bytesread;
  char client;
  char last_read_pending;
  char close_issued;
  char *buf;
  void *context;
  unsigned long long duetime;
  unsigned long long connect_time;
  unsigned long long app_connect_rtt_us;
} cps_socket;

typedef enum
{
  xfer_mode_no_io = 0,           // client disconnects/closes the connection right away (no send/receive)
  xfer_mode_one_io = 1,          // client does 1 send/receive at the beginning
  xfer_mode_continuous_io = 2,   // client keeps doing send/receive
  xfer_mode_continuous_send = 3, // client or server keeps doing send
  xfer_mode_continuous_recv = 4, // client or server keeps doing receive
} data_transfer_mode;

#define DATA_BUF_SIZE 1000

typedef struct
{
  unsigned long long rttsum;
  unsigned long long rttcount;
} cps_rtt_stat;

typedef struct
{
  unsigned long long open_count;         // number of connect or accept requests successfully completed
  unsigned long long open_pending_count; // number of pending connect requests
  unsigned long long open_failure_count; // number of connect or accept requests that failed
  unsigned long long close_count;        // number of connections which have been closed
  unsigned long long iofailure_count;    // number of connections which encountered a send/receive error
  unsigned long long rx_byte_count;      // bytes received across all connections
  unsigned long long tx_byte_count;      // bytes sent across all connections

  unsigned long long retrans_count; // retransmit counter queried from connection right after successful connect

  char wrapped_around_ports;

  // Keep track of RTT stats separately for connections which have been completed
  // with 0 retransmits vs >=1 restransmits
  cps_rtt_stat rtt;
  cps_rtt_stat rttRetrans;
} cps_stat;

typedef union
{
  struct sockaddr_in sa4;
#ifdef WINBUILD
  SOCKADDR_IN6 sa6;
#else
  struct sockaddr_in6 sa6;
#endif
} sockaddr_inet;

typedef struct
{
  utilsw_list_entry link;
  sockaddr_inet local_address;
  sockaddr_inet remote_address;
  unsigned short local_port_start;
  unsigned short local_port_end;
  unsigned short remote_port_start;
  unsigned short remote_port_end;
  int id;
  int thread_count;
  int N;
  int P;
  int connection_duration_ms;
  int continuous_io_period_ms;
  int data_buffer_size;
  int tcpkeepalive_sec;
  data_transfer_mode xfer_mode;
  int proc_index; // -1 means no affinity
  char pollmode;
  char reuseport;
  char disconnect_before_close;
  char abortive_close;
  char donot_reconnect;
  char local_address_specified;
  char xconnect;

  cps_stat stat;
} cps_param;

void dump_thread_params(cps_param *p)
{
  printf("### T %02d : %d/%d %d/%d TC:%d N:%d P:%d D:%d M:%d I:%d L:%d K:%d PM:%d RU:%d DBC:%d AC:%d\n", p->id,
         p->local_port_start, p->local_port_end, p->remote_port_start, p->remote_port_end,
         p->thread_count, p->N, p->P, p->connection_duration_ms, p->xfer_mode, p->continuous_io_period_ms, p->data_buffer_size,
         p->tcpkeepalive_sec, p->pollmode, p->reuseport, p->disconnect_before_close, p->abortive_close);
}

typedef struct
{
  unsigned int time_ms;     // time since T0
  unsigned int retrans : 4; // number of syn retransmits
  unsigned int rtt_us : 28;
} connection_record;

#define MAX_CONN_REC_RTT 10000000    // RTTs larger than this many microsecs are capped for order stats purposes
#define MAX_CONN_BATCH_TRACKED 20000 // Track "time to Nth connection" for up to this value times CONN_BATCH connections
#define CONN_BATCH 100000            // Track "time to Nth connection" with this granularity
unsigned long long connrec_count = 0;
unsigned long long connrec_cutoff_count = 0;
unsigned long long connrec_t0_ms = 0;
unsigned int connrec_cutoff_t_ms = 0;
unsigned int *connrec_rtt_map;  // tracks number of connections per each syn rtt time with microsec granularity
unsigned int *connrec_time_map; // tracks time to 100Kth, 200Kth, etc connection in milliseconds
unsigned long long connrec_rtt_us_sum = 0;
unsigned long long connrec_retrans_sum = 0;
unsigned long long connrec_count_retrans = 0;

void init_connection_recording()
{
  connrec_rtt_map = malloc(sizeof(unsigned int) * (MAX_CONN_REC_RTT + 1));
  if (connrec_rtt_map == NULL)
  {
    fprintf(cps_output_stream, "Failed to allocate connection RTT map\n");
    exit(-1);
  }
  memset(connrec_rtt_map, 0, sizeof(unsigned int) * (MAX_CONN_REC_RTT + 1));

  connrec_time_map = malloc(sizeof(unsigned int) * MAX_CONN_BATCH_TRACKED);
  if (connrec_time_map == NULL)
  {
    fprintf(cps_output_stream, "Failed to allocate connection time map\n");
    exit(-1);
  }
  memset(connrec_time_map, 0, sizeof(unsigned int) * MAX_CONN_BATCH_TRACKED);
}

void start_connection_recording()
{
#ifdef WINBUILD
  InterlockedExchangeAdd64(&connrec_t0_ms, utilsw_get_millisec());
#else
  __sync_add_and_fetch(&connrec_t0_ms, utilsw_get_millisec());
#endif
}

void stop_connection_recording()
{
  unsigned long long t0 = connrec_t0_ms;

#ifdef WINBUILD
  InterlockedExchange64(&connrec_t0_ms, 0);
#else
  __sync_sub_and_fetch(&connrec_t0_ms, connrec_t0_ms);
#endif

#ifdef WINBUILD
  connrec_cutoff_count = InterlockedIncrement64(&connrec_count);
#else
  connrec_cutoff_count = __sync_add_and_fetch(&connrec_count, 1);
#endif

  connrec_cutoff_t_ms = utilsw_get_millisec() - t0;
}

void record_connection(unsigned int retrans, unsigned int rtt_us)
{
  if (connrec_t0_ms == 0)
  {
    return;
  }

#ifdef WINBUILD
  unsigned long long i = InterlockedIncrement64(&connrec_count);
#else
  unsigned long long i = __sync_add_and_fetch(&connrec_count, 1);
#endif

  if ((i % CONN_BATCH) == 0)
  {
    unsigned long long ii = i / CONN_BATCH - 1;
    if (ii < MAX_CONN_BATCH_TRACKED)
    {
      connrec_time_map[ii] = utilsw_get_millisec() - connrec_t0_ms;
    }
  }

#ifdef WINBUILD
  InterlockedExchangeAdd64(&connrec_rtt_us_sum, rtt_us);
#else
  __sync_add_and_fetch(&connrec_rtt_us_sum, rtt_us);
#endif

  if (rtt_us > MAX_CONN_REC_RTT)
  {
    rtt_us = MAX_CONN_REC_RTT;
  }

#ifdef WINBUILD
  InterlockedIncrement(&connrec_rtt_map[rtt_us]);
#else
  __sync_add_and_fetch(&connrec_rtt_map[rtt_us], 1);
#endif

  if (retrans != 0)
  {
#ifdef WINBUILD
    InterlockedExchangeAdd64(&connrec_retrans_sum, retrans);
    InterlockedIncrement64(&connrec_count_retrans);
#else
    __sync_add_and_fetch(&connrec_retrans_sum, retrans);
    __sync_add_and_fetch(&connrec_count_retrans, 1);
#endif
  }
}

void summarize_connection_recording()
{
  unsigned long long n = connrec_cutoff_count - 1;

  if (n <= 0)
  {
    fprintf(cps_output_stream, "\n!!!NO CONNECTIONS WERE ESTABLISHED!!!\n");
    return;
  }

  fprintf(cps_output_stream, "\n");
  fprintf(cps_output_stream, "=== Time (ms) to Nth connection establishment for first %lld connections:\n", n);
  fprintf(cps_output_stream, "=== %7s %7s %7s\n", "N", "T(ms)", "CPS");

  for (unsigned long long i = 0; i < (n / CONN_BATCH) && i < MAX_CONN_BATCH_TRACKED; i++)
  {
    unsigned long long cnt = (i + 1) * CONN_BATCH;
    fprintf(cps_output_stream, "=== %7lld %7d %7lld\n", cnt, connrec_time_map[i], cnt * (unsigned long long)1000 / connrec_time_map[i]);
  }

  if (n % 100000)
  {
    fprintf(cps_output_stream, "=== %7lld %7d %7lld\n", n, connrec_cutoff_t_ms, n * (unsigned long long)1000 / connrec_cutoff_t_ms);
  }

  // Now also print in a more parser-friendly format for automated result reporting

  fprintf(cps_output_stream, "\n###ENDCPS %d\n", (int)(n * (unsigned long long)1000 / connrec_cutoff_t_ms));

  fprintf(cps_output_stream, "\n###CPS");
  for (unsigned long long i = 0; i < (n / CONN_BATCH) && i < MAX_CONN_BATCH_TRACKED; i++)
  {
    unsigned long long cnt = (i + 1) * CONN_BATCH;
    fprintf(cps_output_stream, ",%lld:%d", cnt, connrec_time_map[i]);
  }

  if (n % 100000)
  {
    fprintf(cps_output_stream, ",%lld:%d", n, connrec_cutoff_t_ms);
  }
  fprintf(cps_output_stream, "\n");

  unsigned long long avg = connrec_rtt_us_sum / n;

  int p25 = -1, ip25 = n * 25 / 100;
  int p50 = -1, ip50 = n * 50 / 100; // median
  int p75 = -1, ip75 = n * 75 / 100;
  int p90 = -1, ip90 = n * 90 / 100;
  int p95 = -1, ip95 = n * 95 / 100;
  int p99 = -1, ip99 = n * 99 / 100;
  int p999 = -1, ip999 = n * 999 / 1000;
  int p9999 = -1, ip9999 = n * 9999 / 10000;

  unsigned int cn = 0, cnp = 0;
  for (int i = 0; i <= MAX_CONN_REC_RTT; i++)
  {
    cn += connrec_rtt_map[i];
    if (cnp < ip25 && ip25 <= cn)
      p25 = i;
    if (cnp < ip50 && ip50 <= cn)
      p50 = i;
    if (cnp < ip75 && ip75 <= cn)
      p75 = i;
    if (cnp < ip90 && ip90 <= cn)
      p90 = i;
    if (cnp < ip95 && ip95 <= cn)
      p95 = i;
    if (cnp < ip99 && ip99 <= cn)
      p99 = i;
    if (cnp < ip999 && ip999 <= cn)
      p999 = i;
    if (cnp < ip9999 && ip9999 <= cn)
      p9999 = i;
    cnp = cn;
  }

  fprintf(cps_output_stream, "\n");
  fprintf(cps_output_stream, "=== SYN RTT (us) stats for first %lld connections:\n", n);
  fprintf(cps_output_stream, "=== %8s %8s %8s %8s %8s %8s %8s %8s %8s\n", "P25", "Median", "Mean", "P75", "P90", "P95", "P99", "P99.9", "P99.99");
  fprintf(cps_output_stream, "=== %8d %8d %8d %8d %8d %8d %8d %8d %8d\n", p25, p50, (int)avg, p75, p90, p95, p99, p999, p9999);

  // Now also print in a more parser-friendly format for automated result reporting
  fprintf(cps_output_stream, "\n###SYNRTT");
  fprintf(cps_output_stream, ",%d:%d,%s:%d,%s:%d,%d:%d,%d:%d,%d:%d,%d:%d,%.1f:%d,%.2f:%d\n",
          25, p25,
          "Median", p50,
          "Mean", (int)avg,
          75, p75,
          90, p90,
          95, p95,
          99, p99,
          99.9, p999,
          99.99, p9999);

  fprintf(cps_output_stream, "\n");
  double rtconnpercentage = (double)connrec_count_retrans / (double)n * 100;
  double rtperconn = connrec_count_retrans != 0 ? (double)connrec_retrans_sum / (double)connrec_count_retrans : 0.0;

  fprintf(cps_output_stream, "=== Percentage of connections with retransmits in the first %lld connections: %.4f%%\n", n, rtconnpercentage);
  fprintf(cps_output_stream, "=== Average retransmit count per connection (excluding 0-retransmit cases): %.4f\n", rtperconn);

  fprintf(cps_output_stream, "\n###REXMIT,rtconnpercentage:%.4f,rtperconn:%.4f\n", rtconnpercentage, rtperconn);
}

void accumulate_rx_tx_byte_totals(
    utilsw_list_entry *param_list,
    signed long long *rxtotals,
    signed long long *txtotals)
{
  unsigned long long rx = 0;
  unsigned long long tx = 0;
  utilsw_list_entry *list_entry;

  list_entry = param_list->next;

  while (list_entry != param_list)
  {
    cps_param *param = (cps_param *)list_entry;
    list_entry = list_entry->next;

    cps_stat *statThread = &param->stat;

    rx += statThread->rx_byte_count;
    tx += statThread->tx_byte_count;
  }

  *rxtotals = *rxtotals + rx;
  *txtotals = *txtotals + tx;
}

volatile long pause_all_activity = 0;
volatile long display_brief = 0;

void console_input_thread_fn(void *context)
{
  for (;;)
  {
    int c = getchar();
    switch (c)
    {
    case 'p':
      set_locked(&pause_all_activity, 1);
      printf("PAUSE\n");
      break;
    case 'r':
      set_locked(&pause_all_activity, 0);
      printf("RESUME\n");
      break;
    case 'b':
      switch (display_brief)
      {
      case 0:
        set_locked(&display_brief, 1);
        fprintf(cps_output_stream, "%8s %8s %7s %8s\n", "N", "CPS", "SYNRTT0", "SYNRTTx");
        break;
      case 1:
        set_locked(&display_brief, 2);
        fprintf(cps_output_stream, "CPS\n");
        break;
      case 2:
        set_locked(&display_brief, 0);
        fprintf(cps_output_stream, "%9s %8s %6s %8s %8s %8s %8s %9s %9s %5s %7s %7s %7s %8s\n",
                /*1         2    3       4         5         6         7          8           9            10      11      12         13      14      */
                "T(sec)", "N", "Pend", "Failed", "IOFail", "Conn/s", "Close/s", "RXkbyte/s", "TXkbyte/s", "RT/i", "c0/i", "c0rtt/i", "cR/i", "cRrtt/i");
        break;
      }
      break;
    default:
      break;
    }
  }
}

void init_console_input_thread()
{
  utilsw_thread_t th;
  int rc = utilsw_thread_start(console_input_thread_fn, NULL, &th);
  BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);
exit:
  return;
}

void checkforpause()
{
  while (pause_all_activity != 0)
  {
    utilsw_sleep(100);
  }
}

// TODO: modularize this function
void cps_core_loop(
    cps_param *param)
{
  struct sockaddr *local_address = (struct sockaddr *)&param->local_address;
  struct sockaddr *remote_address = (struct sockaddr *)&param->remote_address;
  const char local_address_specified = param->local_address_specified;
  const char xconnect = param->xconnect;
  const int N = param->N;
  const int connection_duration_ms = param->connection_duration_ms;
  const int continuous_io_period_ms = param->continuous_io_period_ms;
  const data_transfer_mode xfer_mode = param->xfer_mode;
  const int maxPendConnect = param->P;
  const int dataBufferSize = param->data_buffer_size;
  const char pollmode = param->pollmode;
  const char disconnect_before_close = param->disconnect_before_close;
  const char abortive_close = param->abortive_close;
  const char donot_reconnect = param->donot_reconnect;
  const int wait_list_service_rate_per_sec =
      (xfer_mode == xfer_mode_continuous_io && continuous_io_period_ms != 0) ? ((N * 1000) + continuous_io_period_ms - 1) / continuous_io_period_ms : 0;

  // dump_thread_params(param);

  int rc;
  sockwiz_async_waiter_t async_waiter;
  cps_socket *listener = NULL;
  cps_socket *sock;
  sockwiz_async_result res;
  utilsw_list_entry ready_list;
  utilsw_list_entry wait_list;
  utilsw_list_entry connect_pending_limit_list;
  utilsw_list_entry marker_entry;
  utilsw_list_entry *list_entry;

  unsigned long long t;
  unsigned long long last_wait_list_service_time;

  unsigned int localport = 0;
  unsigned int remoteport = 0;
  char signal_wrap_around = 0;

  if (param->proc_index != -1)
  {
    rc = utilsw_set_affinity(param->proc_index);
    BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);
    // printf("#I# T %02d affinity set to %d\n", param->id, param->proc_index);
    param->proc_index = -1;
  }

  utilsw_list_init(&ready_list);
  utilsw_list_init(&wait_list);
  utilsw_list_init(&connect_pending_limit_list);

  rc = sockwiz_async_waiter_create(&async_waiter);
  BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);

  if (remote_address->sa_family == 0)
  {
    const int port_offset = param->reuseport ? 0 : param->id;
    const int port_step = param->reuseport ? 1 : param->thread_count;

    for (unsigned int p = param->local_port_start + port_offset; p <= param->local_port_end; p += port_step)
    {
      // Running in server/listener mode
      listener = (cps_socket *)sockwiz_socket_allocate(
          sockwiz_socket_type_tcp_listener, local_address->sa_family, sizeof(cps_socket));
      BAIL_IF(listener == NULL, -1);

      ((struct sockaddr_in *)local_address)->sin_port = htons((unsigned short)p);

      int listener_flags = param->reuseport ? SOCKWIZ_LISTENER_FLAG_REUSEPORT : 0;
      rc = sockwiz_tcp_listener_open((sockwiz_socket_t)listener, local_address, 1000, listener_flags);
      BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);

      rc = sockwiz_socket_set_async_waiter((sockwiz_socket_t)listener, async_waiter);
      BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);

      listener->action = socket_action_accept;
      utilsw_list_insert_before(&ready_list, &listener->link);
    }
  }
  else
  {
    // Running in client/connector mode
    for (int i = 0; i < N; i++)
    {
      sock = (cps_socket *)sockwiz_socket_allocate(
          sockwiz_socket_type_tcp, local_address->sa_family, sizeof(cps_socket));
      BAIL_IF(sock == NULL, -1);
      sock->action = socket_action_connect;

      if (xfer_mode == xfer_mode_continuous_io && continuous_io_period_ms != 0)
      {
        sock->duetime = utilsw_get_millisec();
        utilsw_list_insert_before(&wait_list, &sock->link);
      }
      else
      {
        utilsw_list_insert_before(&ready_list, &sock->link);
      }
    }

    localport = param->local_port_start;
    remoteport = param->remote_port_start;
    if (xconnect == 0)
    {
      // In default mode, successive client threads connect to successive remote ports
      // (module remote port count). E.g., if we have 2 remote ports (-np 2) and 3 client
      // threads (-r 3), thread 1 always connects to remote port 1, thread 2 always connects
      // to remote port 2, thread 3 always connects to remote port 1. In xconnect mode,
      // each client thread connects to all of the remote ports for each explicitly selected client
      // port number, i.e., it's a full cartesian product, -np times -ncp unique TCP 4-tuples.
      remoteport += param->id % (param->remote_port_end - param->remote_port_start + 1);
    }
  }

  last_wait_list_service_time = 0;

  for (;;)
  {
    if (param->proc_index != -1)
    {
      rc = utilsw_set_affinity(param->proc_index);
      BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);
      // printf("### T %02d affinity set to %d\n", param->id, param->proc_index);
      param->proc_index = -1;
    }

    t = utilsw_get_millisec();

    // Rate limiter burst is capped to 1000ms.
    const int wait_list_drain_cap = min((t - last_wait_list_service_time), 1000) * wait_list_service_rate_per_sec / 1000;
    int wait_list_drain_count = 0;

    // Check if the due time has arrived for any of the waiting sockets

    list_entry = wait_list.next;

    while (list_entry != &wait_list && (wait_list_service_rate_per_sec == 0 || (wait_list_drain_count < wait_list_drain_cap)))
    {
      sock = (cps_socket *)list_entry;
      list_entry = list_entry->next;
      if (t < sock->duetime)
      {
        // Due time has not arrived yet. Since the list is ordered by due time,
        // we can stop here without looking at the remaining entries.
        break;
      }
      // Remove from the wait list and add to the tail of the ready list.
      utilsw_list_remove_entry(&sock->link);
      utilsw_list_insert_before(&ready_list, &sock->link);
      last_wait_list_service_time = t;
      ++wait_list_drain_count;
    }

    // Go through the list of sockets which are currently actionable and
    // take the appropriate actions (i.e., accept, connect, send, recv, close).
    // Since outcome of an action may lead to a new action being queued inline,
    // we need to be careful about continously processing the actionable socket
    // list without peeking at the completions on the async_waiter; thus, we
    // insert a marker to delinetate the items enqueued inline, which we'll
    // process in the next iteration after draining the async_waiter.

    utilsw_list_insert_before(&ready_list, &marker_entry);
    list_entry = ready_list.next;

#define BATCH_SIZE 10
    int batch_count = 0;

    while (list_entry != &marker_entry && batch_count < BATCH_SIZE)
    {
      sock = (cps_socket *)list_entry;
      list_entry = list_entry->next;
      utilsw_list_remove_entry(&sock->link);
      ++batch_count;

      switch (sock->action)
      {

      case socket_action_close:
      {
        char client = sock->client;
        if (sock->close_issued == 0)
        {
          sock->close_issued = 1;

          if (sock->completion_status != SOCKWIZ_SUCCESS)
          {
            sockwiz_tcp_close((sockwiz_socket_t)sock, SOCKWIZ_TCP_CLOSE_ABORTIVE);
          }
          else
          {
            if (disconnect_before_close)
            {
              sockwiz_tcp_disconnect((sockwiz_socket_t)sock);
            }
            sockwiz_tcp_close((sockwiz_socket_t)sock, abortive_close ? SOCKWIZ_TCP_CLOSE_ABORTIVE : 0);
          }
          ++param->stat.close_count;
        }
        if (sock->last_read_pending == 0)
        {
          if (sock->completion_status != SOCKWIZ_SUCCESS)
          {
            ++param->stat.iofailure_count;
          }
          free(sock->buf);
          sockwiz_socket_free((sockwiz_socket_t)sock);
          if (client && !donot_reconnect)
          {
            // Client initiates a new connection for each closed connection.
            sock = (cps_socket *)sockwiz_socket_allocate(
                sockwiz_socket_type_tcp, local_address->sa_family, sizeof(cps_socket));
            BAIL_IF(sock == NULL, -1);
            sock->action = socket_action_connect;
            utilsw_list_insert_before(&ready_list, &sock->link);
          }
        }
        break;
      }

      case socket_action_connect:
      {
        if (param->stat.open_pending_count >= maxPendConnect)
        {
          // Put the socket into connect_pending_limit_list.
          utilsw_list_insert_before(&connect_pending_limit_list, &sock->link);
          break;
        }

        sock->client = 1;
        rc = sockwiz_socket_set_async_waiter((sockwiz_socket_t)sock, async_waiter);
        BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);
        sock->app_connect_rtt_us = utilsw_get_microsec();
        ++param->stat.open_pending_count;

        ((struct sockaddr_in *)local_address)->sin_port = htons((unsigned short)localport);
        ((struct sockaddr_in *)remote_address)->sin_port = htons((unsigned short)remoteport);

        // printf("### T %02d %d %d\n", param->id, localport, remoteport);fflush(stdout);
        if (signal_wrap_around)
        {
          param->stat.wrapped_around_ports = 1;
          signal_wrap_around = 0;
        }

        rc = sockwiz_tcp_connect(
            (sockwiz_socket_t)sock,
            localport == 0 && local_address_specified == 0 ? NULL : local_address,
            remote_address,
            localport == 0 ? 0 : SOCKWIZ_TCP_CONNECT_FLAG_REUSEADDR);
        if (rc != SOCKWIZ_PENDING)
        {
          --param->stat.open_pending_count;
          sock->completion_status = rc;
          if (sock->completion_status == SOCKWIZ_SUCCESS)
          {
            BAILMSG_IF(1, "Connect inline success unexpected here");
            //++param->stat.open_count;
            // sock->app_connect_rtt_us = utilsw_get_microsec() - sock->app_connect_rtt_us;
          }
          else
          {
#ifdef WINBUILD
            ++param->stat.open_failure_count;
#else
            if (rc != 99) // Ignore inline EADDRNOTAVAIL errors on Linux.
            {
              ++param->stat.open_failure_count;
            }
#endif
          }
          sock->action = socket_action_connect_complete;
          utilsw_list_insert_before(&ready_list, &sock->link);
        }

        char inc_local_port = !xconnect;
        if (xconnect && ++remoteport > param->remote_port_end)
        {
          remoteport = param->remote_port_start;
          inc_local_port = 1;
        }

        if (localport != 0 && inc_local_port && ++localport > param->local_port_end)
        {
          localport = param->local_port_start;
          signal_wrap_around = 1;
        }

        break;
      }

      case socket_action_connect_complete:
      {
        if (param->stat.open_pending_count < maxPendConnect && utilsw_list_is_empty(&connect_pending_limit_list) == 0)
        {
          // Remove a socket from connect_pending_limit_list and put back into ready_list.
          utilsw_list_entry *connect_wait_list_entry = connect_pending_limit_list.next;
          utilsw_list_remove_entry(connect_wait_list_entry);
          utilsw_list_insert_before(&ready_list, connect_wait_list_entry);
        }

        if (sock->completion_status != SOCKWIZ_SUCCESS)
        {
          sockwiz_socket_free((sockwiz_socket_t)sock);
          sock = (cps_socket *)sockwiz_socket_allocate(
              sockwiz_socket_type_tcp, local_address->sa_family, sizeof(cps_socket));
          BAIL_IF(sock == NULL, -1);
          sock->action = socket_action_connect;
          utilsw_list_insert_before(&ready_list, &sock->link);
          break;
        }

        if (param->tcpkeepalive_sec > 0)
        {
          rc = sockwiz_tcp_set_keepalive((sockwiz_socket_t)sock, param->tcpkeepalive_sec);
          BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);
        }

        sock->connect_time = t;
        sock->buf = malloc(dataBufferSize);
        BAIL_IF(sock->buf == NULL, -1);

        if (xfer_mode == xfer_mode_no_io)
        {
          sock->action = socket_action_close;

          if (connection_duration_ms != 0)
          {
            sock->bytesread = 1;
            rc = sockwiz_read((sockwiz_socket_t)sock, sock->buf, &sock->bytesread, NULL);
            if (rc != SOCKWIZ_PENDING)
            {
              sock->completion_status = SOCKWIZ_FAILURE;
            }
            else
            {
              sock->last_read_pending = 1;
              sock->duetime = sock->connect_time + connection_duration_ms;
              utilsw_list_insert_before(&wait_list, &sock->link);
              break;
            }
          }
        }
        else
        {
          // Add the new socket to the ready list with read or write action.
          sock->bytesread = dataBufferSize;
          sock->action = xfer_mode == xfer_mode_continuous_recv ? socket_action_read : socket_action_write;
        }
        utilsw_list_insert_before(&ready_list, &sock->link);
        break;
      }

      case socket_action_accept: // action on listener
      {
        cps_socket *newsock = (cps_socket *)sockwiz_socket_allocate(
            sockwiz_socket_type_tcp, local_address->sa_family, sizeof(cps_socket));
        BAIL_IF(newsock == NULL, -1);
        newsock->context = sock; // remember the listener
        rc = sockwiz_tcp_accept((sockwiz_socket_t)sock, (sockwiz_socket_t)newsock, NULL);
        if (rc != SOCKWIZ_PENDING)
        {
          // Add the listener back to ready list head to accept more connections.
          assert(sock->action = socket_action_accept);
          utilsw_list_insert_before(ready_list.next, &sock->link);

          newsock->completion_status = rc;
          if (newsock->completion_status == SOCKWIZ_SUCCESS)
          {
            ++param->stat.open_count;
          }
          else
          {
            ++param->stat.open_failure_count;
          }

          newsock->action = socket_action_accept_complete;
          utilsw_list_insert_before(&ready_list, &newsock->link);
        }
        break;
      }

      case socket_action_accept_complete: // action on accepted socket
      {
        sock->context = NULL;
        if (sock->completion_status != SOCKWIZ_SUCCESS)
        {
          sockwiz_socket_free((sockwiz_socket_t)sock);
          break;
        }

        unsigned int rtt;
        unsigned int synRetrans;

        rc = sockwiz_tcp_get_info((sockwiz_socket_t)sock, &rtt, &synRetrans);
        BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);

        if (param->tcpkeepalive_sec > 0)
        {
          rc = sockwiz_tcp_set_keepalive((sockwiz_socket_t)sock, param->tcpkeepalive_sec);
          BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);
        }

        record_connection(synRetrans, rtt);

        if (synRetrans > 0)
        {
          param->stat.retrans_count += synRetrans;
          param->stat.rttRetrans.rttsum += rtt;
          param->stat.rttRetrans.rttcount++;
        }
        else
        {
          param->stat.rtt.rttsum += rtt;
          param->stat.rtt.rttcount++;
        }

        rc = sockwiz_socket_set_async_waiter((sockwiz_socket_t)sock, async_waiter);
        BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);

        sock->buf = malloc(dataBufferSize);
        BAIL_IF(sock->buf == NULL, -1);

        // Add the new socket to the ready list with read or write action.
        sock->bytesread = dataBufferSize;
        sock->action = xfer_mode == xfer_mode_continuous_send ? socket_action_write : socket_action_read;
        utilsw_list_insert_before(&ready_list, &sock->link);
        break;
      }

      case socket_action_read:
      {
        sock->bytesread = dataBufferSize;
        rc = sockwiz_read((sockwiz_socket_t)sock, sock->buf, &sock->bytesread, NULL);
        if (rc != SOCKWIZ_PENDING)
        {
          sock->completion_status = rc;
          sock->action = socket_action_read_complete;
          utilsw_list_insert_before(&ready_list, &sock->link);
        }
        break;
      }

      case socket_action_read_complete:
      {
        if (sock->completion_status == SOCKWIZ_SUCCESS)
        {
          param->stat.rx_byte_count += sock->bytesread;
        }
        sock->action =
            (sock->completion_status != SOCKWIZ_SUCCESS || sock->bytesread == 0) ? socket_action_close : (xfer_mode == xfer_mode_continuous_recv ? socket_action_read : socket_action_write);

        if (sock->action != socket_action_close && sock->client)
        {
          if (xfer_mode == xfer_mode_one_io)
          {
            sock->action = socket_action_close;
            if (connection_duration_ms != 0)
            {
              sock->bytesread = 1;
              rc = sockwiz_read((sockwiz_socket_t)sock, sock->buf, &sock->bytesread, NULL);
              if (rc != SOCKWIZ_PENDING)
              {
                sock->completion_status = SOCKWIZ_FAILURE;
              }
              else
              {
                sock->last_read_pending = 1;
                sock->duetime = sock->connect_time + connection_duration_ms;
                utilsw_list_insert_before(&wait_list, &sock->link);
                break;
              }
            }
          }
          else if ((t - sock->connect_time) >= connection_duration_ms)
          {
            sock->action = socket_action_close;
          }
          else if (xfer_mode == xfer_mode_continuous_io && continuous_io_period_ms != 0)
          {
            sock->duetime = utilsw_get_millisec() + continuous_io_period_ms;
            utilsw_list_insert_before(&wait_list, &sock->link);
            break;
          }
        }

        utilsw_list_insert_before(&ready_list, &sock->link);
        break;
      }

      case socket_action_write:
      {
        rc = sockwiz_write((sockwiz_socket_t)sock, sock->buf, sock->bytesread, NULL);
        if (rc != SOCKWIZ_PENDING)
        {
          sock->completion_status = rc;
          sock->action = socket_action_write_complete;
          utilsw_list_insert_before(&ready_list, &sock->link);
        }
        break;
      }

      case socket_action_write_complete:
      {
        if (sock->completion_status == SOCKWIZ_SUCCESS)
        {
          param->stat.tx_byte_count += sock->bytesread;
        }
        sock->action =
            (sock->completion_status != SOCKWIZ_SUCCESS) ? socket_action_close : (xfer_mode == xfer_mode_continuous_send ? socket_action_write : socket_action_read);

        if (sock->action != socket_action_close && sock->client && xfer_mode == xfer_mode_continuous_send)
        {
          if ((t - sock->connect_time) >= connection_duration_ms)
          {
            sock->action = socket_action_close;
          }
        }

        utilsw_list_insert_before(&ready_list, &sock->link);
        break;
      }

      default:
        BAIL_IF(0, -1);
      }
    }

    utilsw_list_remove_entry(&marker_entry);

    // Drain pending operations, and update the actionable socket list accordingly.
    // We will drain all completed operations, but will not actually do a blocking
    // wait while there are actionable sockets already. We wait at most 100ms in order
    // to support a granularity of ~100ms for honoring the requested connection duration
    // for each socket.

    for (;;)
    {
      rc = sockwiz_async_waiter_wait(
          async_waiter,
          (!utilsw_list_is_empty(&ready_list) ||
           (pollmode && ((param->stat.open_count - param->stat.close_count) > 0)))
              ? 0
              : 100,
          &res);
      if (rc == SOCKWIZ_TIMEOUT)
      {
        break;
      }

      BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);

      checkforpause();

      sock = (cps_socket *)res.sock;
      sock->completion_status = res.failed ? res.info : SOCKWIZ_SUCCESS;

      switch (res.type)
      {

      case sockwiz_async_connect:
        --param->stat.open_pending_count;
        if (!res.failed)
        {
          unsigned int rtt;
          unsigned int synRetrans;

          ++param->stat.open_count;
          sock->app_connect_rtt_us = utilsw_get_microsec() - sock->app_connect_rtt_us;

          rc = sockwiz_tcp_get_info((sockwiz_socket_t)sock, &rtt, &synRetrans);
          BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);

          record_connection(synRetrans, rtt);

          if (synRetrans > 0)
          {
            param->stat.retrans_count += synRetrans;
            param->stat.rttRetrans.rttsum += rtt;
            param->stat.rttRetrans.rttcount++;
          }
          else
          {
            param->stat.rtt.rttsum += rtt;
            param->stat.rtt.rttcount++;
          }
        }
        else
        {
          ++param->stat.open_failure_count;
        }

        sock->action = socket_action_connect_complete;
        break;

      case sockwiz_async_accept:

        // Add the listener back to ready list head to accept more connections.
        listener = (cps_socket *)sock->context;
        assert(listener->action = socket_action_accept);
        utilsw_list_insert_before(ready_list.next, &listener->link);

        if (sock->completion_status == SOCKWIZ_SUCCESS)
        {
          ++param->stat.open_count;
        }
        else
        {
          ++param->stat.open_failure_count;
        }

        sock->action = socket_action_accept_complete;
        break;

      case sockwiz_async_read:
        if (sock->last_read_pending)
        {
          sock->action = socket_action_close;
          sock->last_read_pending = 0;
          if (sock->close_issued)
          {
            sock->completion_status = SOCKWIZ_SUCCESS;
          }
          else
          {
            sock->completion_status = SOCKWIZ_FAILURE;
            // remove from wait_list
            utilsw_list_remove_entry(&sock->link);
          }
        }
        else
        {
          sock->bytesread = res.failed ? 0 : res.info;
          sock->action = socket_action_read_complete;
        }
        break;

      case sockwiz_async_write:
        sock->action = socket_action_write_complete;
        break;

      default:
        BAIL_IF(0, -1);
      }

      utilsw_list_insert_before(&ready_list, &sock->link);
    }
  }

exit:

  exit(-1);
}

void cps_thread_fn(void *context)
{
  cps_core_loop((cps_param *)context);
}

#define ALIGN_UP(x, a) ((((unsigned int)(x)) + (a) - 1) & (~((a) - 1)))

void print_commandline(int argc, char **argv)
{
  fprintf(cps_output_stream, "\n=== CMDLINE:");
  for (int i = 0; i < argc; i++)
  {
    fprintf(cps_output_stream, " %s", argv[i]);
  }
  fprintf(cps_output_stream, "\n");
  fprintf(cps_output_stream, "\n=== VERSION %d.%d\n", NCPS_MAJOR_VERSION, NCPS_MINOR_VERSION);
}

// 1 means success, 0 means failure
int read_ip_address(const char *str, sockaddr_inet *sa)
{
  int rc;
  rc = inet_pton(AF_INET, str, &sa->sa4.sin_addr);
  if (rc == 1)
  {
    sa->sa4.sin_family = AF_INET;
  }
  else
  {
    rc = inet_pton(AF_INET6, str, &sa->sa6.sin6_addr);
    if (rc == 1)
    {
      sa->sa6.sin6_family = AF_INET6;
    }
  }
  return rc;
}

#define MAX_NUM_PROCS 1024

typedef struct
{
  int numprocs;
  unsigned long long per_proc_rss_activity[MAX_NUM_PROCS];
} RSS_ACTIVITY_TRACKER;

char netrx_line[65536] = {0};

int snap_rss_activity(RSS_ACTIVITY_TRACKER *rss_activity)
{
  int rc = -1;
  rss_activity->numprocs = 0;

#ifndef WINBUILD

  const char *prefix = "NET_RX:";
  char *netrx_str;

  FILE *f = fopen("/proc/softirqs", "r");
  BAIL_IF(f == NULL, errno);

  for (;;)
  {
    BAIL_IF(fgets(netrx_line, sizeof(netrx_line), f) == NULL, errno);
    netrx_str = strstr(netrx_line, prefix);
    if (netrx_str != NULL)
      break;
  }

  netrx_str += strlen(prefix);

  char *endptr = NULL;
  for (;;)
  {
    unsigned long long ll = strtoull(netrx_str, &endptr, 10);
    if (endptr != netrx_str)
    {
      BAILMSG_IF(rss_activity->numprocs == MAX_NUM_PROCS, "!!! more than 1024 processors");
      rss_activity->per_proc_rss_activity[rss_activity->numprocs++] = ll;
      netrx_str = endptr;
      BAILMSG_IF(!(isspace(*netrx_str) || *netrx_str == 0), "!!! invalid number");
    }
    else
    {
      break;
    }
  }

  rc = 0;

exit:

  if (f != NULL)
  {
    fclose(f);
  }

#else

  fprintf(cps_output_stream, "RSS activity tracking not yet supported on Windows\n");

#endif

  return rc;
}

unsigned long long rss_activity_threshold(RSS_ACTIVITY_TRACKER *rss0, RSS_ACTIVITY_TRACKER *rss1)
{
  //
  // We expect see a bimodal distribution for rss activity. Deltas for RSS procs will be high,
  // and deltas for non-RSS procs will be low or zero. A quick and dirty method to find a good
  // threshold value that partitions (separates) the two modes is to find the max delta first,
  // and then take a small enough fraction of it, like 10%, and consider any delta value below
  // this threshold to reflect a non-RSS proc, and others refelct RSS procs. 10% is arbitrary,
  // but works OK for Linux RSS activity since RSS activity is counted as number of NET_RX soft
  // IRQs, which is virtually zero on non-RSS procs.
  //
  unsigned long long max = 0;
  unsigned long long val = 0;

  for (int i = 0; i < rss1->numprocs; i++)
  {
    val = rss1->per_proc_rss_activity[i] - rss0->per_proc_rss_activity[i];
    if (val > max)
    {
      max = val;
    }
  }

  return max / 10;
}

// < 0 : failure
// 0: success and continue calling
// 1: success and stop calling
int track_rss_and_adjust_affinity(utilsw_list_entry *param_list, double cps)
{
  int rc = -1;
  static int epoch = 0;
  static const int max_epochs = 3;
  static const double cpsbar = 10000;
  static RSS_ACTIVITY_TRACKER rss0, rss1;

  //
  // Snap initial RSS activity as soon as we see > 10K CPS.
  // If we see >10K cps 3 times consecutively, snap RSS activity again, use the per proc delta
  // counts to figure out procs that are NOT getting RSS activity and affinitize the threads to
  // them, and stop tracking RSS. The set affinities will stick until process termination.
  // If we see cps fall below 10K, abandon RSS tracking and wait for it to go above 10K again.
  //

  if (cps >= cpsbar)
  {
    if (epoch == 0)
    {
      BAILMSG_IF(snap_rss_activity(&rss0), "!!! failed to query initial rss activity");
    }

    ++epoch;

    if (epoch == max_epochs)
    {
      BAILMSG_IF(snap_rss_activity(&rss1), "!!! failed to query last rss activity");
      BAILMSG_IF(rss1.numprocs != rss0.numprocs, "!!! rss acivity processor count mismatch");

      const unsigned long long rss_thresh = rss_activity_threshold(&rss0, &rss1);
      char *outstr = netrx_line;
      int adv;

      netrx_line[1] = 0;

      utilsw_list_entry *le = param_list->next;
      for (int i = 0; i < rss1.numprocs && le != param_list; i++)
      {
        if ((rss1.per_proc_rss_activity[i] - rss0.per_proc_rss_activity[i]) < rss_thresh)
        {
          cps_param *param = (cps_param *)le;
          le = le->next;
          param->proc_index = i;
          adv = sprintf(outstr, ",%d", i);
          outstr += adv;
          continue;
        }
      }

      fprintf(cps_output_stream, "AFFINITY: %s\n", netrx_line + 1);
      BAILMSG_IF(le != param_list, "!!! not enough non-rss processors");

      rc = 1;
      goto exit;
    }
  }
  else
  {
    epoch = 0;
  }

  rc = 0;

exit:

  return rc;
}

#define MAX_THREADS 1024

#define DEFAULT_THREAD_COUNT 16

int main(int argc, char **argv)
{
  utilsw_list_entry param_list;
  utilsw_list_entry *list_entry;
  cps_param *param;
  FILE *outstream = NULL;

  cps_output_stream = stdout;
  utilsw_set_output_stream(stdout);

#ifdef WINBUILD
  WSADATA wsd;
  int rc = WSAStartup(MAKEWORD(2, 2), &wsd);
  BAIL_IF(rc != 0, rc)
#else
  signal(SIGPIPE, SIG_IGN);
#endif

  if (argc < 2)
  {
    printf("VERSION %d.%d\n", NCPS_MAJOR_VERSION, NCPS_MINOR_VERSION);
    printf("\n");
    printf("ncps -s : run as server with the following options:\n");
    printf("    -r <thread count> : (default: %d)\n", DEFAULT_THREAD_COUNT);
    printf("    -b <IP address to bind to> : (default: 0.0.0.0)\n");
    printf("    -np <number of TCP ports to listen on> : (default: thread count)\n");
    printf("    -bp <base TCP port number to listen on> : (default: 10001)\n");
    printf("        E.g.: For -bp 20000 -np 100 -r 3, the 3 threads listen on the following port numbers:\n");
    printf("              Thread-1: 20000, 20003, 20006,..., 20096, 20099\n");
    printf("              Thread-2: 20001, 20004, 20007,..., 20097\n");
    printf("              Thread-3: 20002, 20005, 20008,..., 20098\n");
    printf("    -M <data transfer mode> : (default: client-driven)\n");
    printf("            s: continuous send, r: continuous receive\n");
    printf("\n");
    printf("ncps -c <IP address to connect to> : run as client with the following options:\n");
    printf("    -r <thread count> : (default: %d)\n", DEFAULT_THREAD_COUNT);
    printf("    -b <IP address to bind to> : (default: 0.0.0.0)\n");
    printf("    -bp <base remote TCP port number to connect to> : (default: 10001)\n");
    printf("    -np <number of remote TCP ports to connect to> : (default: thread count)\n");
    printf("        Tip: The port range specified by a client's -bp/-np parameters must be a subset of the range\n");
    printf("             specified by the server's -bp/-np parameters.\n");
    printf("    -bcp <base local TCP port number to bind to> : (default: 0 -- local ephemeral ports picked by TCPIP)\n");
    printf("    -ncp <number of local TCP ports to bind to> : (ignored if -bcp == 0, must be specified otherwise)\n");
    printf("       If client specifies an explicit local port range via -bcp and -ncp parameters, this local port range\n");
    printf("       is divided across client threads and each thread explicitly binds (with SO_REUSEADDR) to the local ports\n");
    printf("       in its range for initiating connections. E.g.: For -bcp 30000 -ncp 40 -r 3, 3 threads behave as:\n");
    printf("              Thread-1 uses local port numbers in the 30000-30013 range (14 local ports)\n");
    printf("              Thread-2 uses local port numbers in the 30014-30026 range (13 local ports)\n");
    printf("              Thread-3 uses local port numbers in the 30027-30039 range (13 local ports)\n");
    printf("    -xconnect : This option changes how client threads choose the remote ports to connect to.\n");
    printf("       By default, each client thread initiates connections to only one remote port. E.g., with -bp A,\n");
    printf("       thread1 connects to remote port A, thread2 to A+1 (modulo -np), thread3 to A+2 (module -np), and so on.\n");
    printf("       With -xconnect, each client thread connects to all the ports specified by -bp/-np.\n");
    printf("       When used with -bcp/-ncp parameters, each client thread uses each local port in its range to connect\n");
    printf("       to each remote port. E.g., thread1 connects from 30000 to 20000, then 30000 to 20001,..., then 30000 to 20099,\n");
    printf("       and repeats this for all the  other local ports in its own range. This is performed by all client threads for\n");
    printf("       their own local port ranges. This means first '-ncp times -np' TCP connections will all have unique 4-tuples.\n");
    printf("    -N <total number of connections to keep open> : (default: thread count * 100)\n");
    printf("    -P <max number of pending connect requests at any given time> : (default: N)\n");
    printf("    -D <duration in milliseconds for each connection> : (default: 0)\n");
    printf("    -M <data transfer mode> : (default: 1)\n");
    printf("       0: no send/receive, 1: one send/receive, p: ping/pong (continuous send/receive)\n");
    printf("       s: continuous send, r: continuous receive\n");
    printf("\n");
    printf("Other options:\n");
    printf("  -aff <comma-separated processor indices for thread affinity> : th1 to val1, th2 to val2,... (default: no affinity)\n");
    printf("       On Linux, you can specify 'nonrss' to automatically detect non-RSS processors and affinitize to them.\n");
    printf("  -rup : use the SO_REUSEPORT option on listener sockets. All threads listen on all the sockets.\n");
    printf("  -tka <idle_sec>: enable TCP keep-alive on all connections with an idle period idle_sec seconds.\n");
    printf("  -dnrc : client-only - Once a connection is successfully established, do not reconnect after it's closed.\n");
    printf("  -t <duration_sec> : stop and report final stats after this many seconds. (default: run forever)\n");
    printf("  -i <display_interval_sec> : display various current stats with this period. (default: 1)\n");
    printf("  -k <mode_p_interval_sec> : client only - seconds to wait between send/receive attempts in mode p. (default: 0)\n");
    printf("                             This also rate-limits the connects HENCE SHOULD NOT be used for max CPS measurements.\n");
    printf("  -abortiveclose : Terminate the TCP connection by issuing an abortive close-socket (default on server side)\n");
    printf("  -normalclose   : Terminate the TCP connection by issuing a normal close-socket (default on client side)\n");
    printf("  -disconbc      : Issue an explicit graceful disconnect before close-socket.\n");
    printf("  -nodisconbc    : Do not issue an explicit graceful disconnect before close-socket (default on both sides)\n");
    printf("  -ds <delay_start_sec> : start connection activity after this many seconds from program launch. (default: 0)\n");
    printf("  -wt <warm_up_seconds> : skip this many seconds when reporting the final stats at the end. (default: 0)\n");
    printf("  -sil : silent-mode; do not print stats periodically during the run\n");
    printf("  -o <output_file_name> : direct all output to the specified file. (default: stdout)\n");
    printf("  -len <send_or_receive_size> : issue sends and receives with this size. (default: %d)\n", DATA_BUF_SIZE);
    printf("  -poll : poll for send and receive completions\n");
    printf("  -brief : display only CPS and SYN-RTT in the periodic output\n");
    printf("\n");
    exit(-1);
  }

  utilsw_list_init(&param_list);

  BAILMSG_IF(strcmp(argv[1], "-s") != 0 && strcmp(argv[1], "-c") != 0, "specify -s or -c first");
  int server = (strcmp(argv[1], "-s") == 0);

  int argi = 2;
  sockaddr_inet la = {0};
  sockaddr_inet ra = {0};
  int np = 0;
  int bp = 10001;
  int ncp = 0;
  int bcp = 0;
  int N = 0;
  int P = 0;
  int D = 0;
  data_transfer_mode M = xfer_mode_one_io;
  int display_interval_ms = 1000;
  int continuous_io_period_ms = 0;
  int duration_ms = 0;
  int delay_start_ms = 0;
  int thread_count = DEFAULT_THREAD_COUNT;
  int skip_milliseconds = 0;
  int silent = 0;
  int pollmode = 0;
  int reuseport = 0;
  int disconnect_before_close = 0;
  int abortive_close = server ? 1 : 0;
  int donot_reconnect = 0;
  int tcpkeepalive_sec = 0;
  int data_buffer_size = DATA_BUF_SIZE;
  int aff[MAX_THREADS];
  int affcount = 0;
  char local_address_specified = 0;
  char xconnect = 0;

  la.sa4.sin_family = AF_INET;

  if (!server)
  {
    BAILMSG_IF(argi == argc, "-c must be followed by an IP address");
    int rc = read_ip_address(argv[argi], &ra);
    BAILMSG_IF(rc != 1, "Invalid remote IP address");
    la.sa4.sin_family = ra.sa4.sin_family;
    argi++;
  }

  while (argi < argc)
  {
    char *arg = argv[argi];

    if (strcmp(arg, "-b") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-b requires an IP address");
      int rc = read_ip_address(argv[argi], &la);
      BAILMSG_IF(rc != 1, "Invalid local IP address");
      BAILMSG_IF(!server && (la.sa4.sin_family != ra.sa4.sin_family), "local and remote address families do not match");
      local_address_specified = 1;
    }
    else if (strcmp(arg, "-aff") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-aff requires a comma-separated list of processor index values or 'nonrss'");
      if (strcmp(argv[argi], "nonrss") == 0)
      {
        affcount = -1;
      }
      else
      {
        char *pch = strtok(argv[argi], ",");
        while (pch != NULL && affcount < MAX_THREADS)
        {
          if (strcmp(pch, "x") == 0) // ignore remainder
            break;
          int procidx = atoi(pch);
          BAILMSG_IF(procidx < 0, "Cannot provide negative proc index");
          aff[affcount++] = procidx;
          pch = strtok(NULL, ",");
        }
        BAILMSG_IF(pch != NULL && strcmp(pch, "x"), "Too many proc index values specified")
      }
    }
    else if (strcmp(arg, "-np") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-np requires a positive integer value");
      np = atoi(argv[argi]);
      BAILMSG_IF(np < 1 || np > 65535, "-np value must be between 1-65535");
    }
    else if (strcmp(arg, "-bp") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-bp requires a TCP port number");
      bp = atoi(argv[argi]);
      BAILMSG_IF(bp < 1 || bp > 65535, "-bp value must be between 1-65535");
    }
    else if (strcmp(arg, "-ncp") == 0)
    {
      argi++;
      BAILMSG_IF(server, "-ncp is not a valid server option");
      BAILMSG_IF(argi == argc, "-ncp requires a positive integer value");
      ncp = atoi(argv[argi]);
      BAILMSG_IF(ncp < 1 || ncp > 65535, "-ncp value must be between 1-65535");
    }
    else if (strcmp(arg, "-bcp") == 0)
    {
      argi++;
      BAILMSG_IF(server, "-bcp is not a valid server option");
      BAILMSG_IF(argi == argc, "-bcp requires a TCP port number");
      bcp = atoi(argv[argi]);
      BAILMSG_IF(bcp < 0 || bcp > 65535, "-bcp value must be between 0-65535");
    }
    else if (strcmp(arg, "-xconnect") == 0)
    {
      BAILMSG_IF(server, "-xconnect is not a valid server option");
      xconnect = 1;
    }
    else if (strcmp(arg, "-N") == 0)
    {
      argi++;
      BAILMSG_IF(server, "-N is not a valid server option");
      BAILMSG_IF(argi == argc, "-N requires a positive integer value");
      N = atoi(argv[argi]);
      BAILMSG_IF(N < 1, "-N value must be positive");
    }
    else if (strcmp(arg, "-P") == 0)
    {
      argi++;
      BAILMSG_IF(server, "-P is not a valid server option");
      BAILMSG_IF(argi == argc, "-P requires a positive integer value");
      P = atoi(argv[argi]);
      BAILMSG_IF(P < 1, "-P value must be positive");
    }
    else if (strcmp(arg, "-D") == 0)
    {
      argi++;
      BAILMSG_IF(server, "-D is not a valid server option");
      BAILMSG_IF(argi == argc, "-D requires a non-negative integer value");
      D = atoi(argv[argi]);
      BAILMSG_IF(D < 0, "-D value must be non-negative");
    }
    else if (strcmp(arg, "-M") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-M requires a value");
      switch (argv[argi][0])
      {
      case '0':
        M = xfer_mode_no_io;
        break;
      case '1':
        M = xfer_mode_one_io;
        break;
      case 'p':
        M = xfer_mode_continuous_io;
        break;
      case 's':
        M = xfer_mode_continuous_send;
        break;
      case 'r':
        M = xfer_mode_continuous_recv;
        break;
      default:
        BAILMSG_IF(1, "-M value must be one of 0, 1, p, s, r")
      }
      BAILMSG_IF(server && M != xfer_mode_continuous_recv && M != xfer_mode_continuous_send,
                 "Only s and r can be specified on server as -M values");
    }
    else if (strcmp(arg, "-i") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-i requires a time value in seconds");
      display_interval_ms = atoi(argv[argi]) * 1000;
    }
    else if (strcmp(arg, "-t") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-t requires a time value in seconds");
      duration_ms = atoi(argv[argi]) * 1000;
      BAILMSG_IF(duration_ms < 1000, "-t requires a value >= 1");
    }
    else if (strcmp(arg, "-r") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-r requires a value");
      thread_count = atoi(argv[argi]);
      BAILMSG_IF(thread_count < 1 || thread_count > MAX_THREADS, "bad thread count");
    }
    else if (strcmp(arg, "-ds") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-ds requires a time value in seconds");
      delay_start_ms = atoi(argv[argi]) * 1000;
      BAILMSG_IF(delay_start_ms < 1000, "-ds requires a value >= 1");
    }
    else if (strcmp(arg, "-wt") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-wt requires a time value in seconds");
      skip_milliseconds = atoi(argv[argi]) * 1000;
      BAILMSG_IF(skip_milliseconds < 0, "-wt requires a value >= 0");
    }
    else if (strcmp(arg, "-len") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-len requires a byte count value");
      data_buffer_size = atoi(argv[argi]);
      BAILMSG_IF(data_buffer_size < 0, "-len requires a value >= 0");
      if (data_buffer_size == 0)
      {
        data_buffer_size = DATA_BUF_SIZE;
      }
    }
    else if (strcmp(arg, "-k") == 0)
    {
      argi++;
      BAILMSG_IF(server, "-k is not a valid server option");
      BAILMSG_IF(argi == argc, "-k requires a value in seconds");
      continuous_io_period_ms = atoi(argv[argi]) * 1000;
      BAILMSG_IF(continuous_io_period_ms < 0, "-k requires a value >= 0");
    }
    else if (strcmp(arg, "-tka") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-tka requires an idle_sec value");
      tcpkeepalive_sec = atoi(argv[argi]);
      BAILMSG_IF(tcpkeepalive_sec < 0, "-tka requires a value >= 0");
    }
    else if (strcmp(arg, "-dnrc") == 0)
    {
      donot_reconnect = 1;
    }
    else if (strcmp(arg, "-sil") == 0)
    {
      silent = 1;
    }
    else if (strcmp(arg, "-poll") == 0)
    {
      pollmode = 1;
    }
    else if (strcmp(arg, "-rup") == 0)
    {
      BAILMSG_IF(!server, "-rup is not a valid client option");
      reuseport = 1;
    }
    else if (strcmp(arg, "-abortiveclose") == 0)
    {
      abortive_close = 1;
    }
    else if (strcmp(arg, "-normalclose") == 0)
    {
      abortive_close = 0;
    }
    else if (strcmp(arg, "-disconbc") == 0)
    {
      disconnect_before_close = 1;
    }
    else if (strcmp(arg, "-nodisconbc") == 0)
    {
      disconnect_before_close = 0;
    }
    else if (strcmp(arg, "-brief") == 0)
    {
      display_brief = 1;
    }
    else if (strcmp(arg, "-o") == 0)
    {
      argi++;
      BAILMSG_IF(argi == argc, "-o requires a file name");
      outstream = fopen(argv[argi], "w");
      BAILMSG_IF(outstream == NULL, "Could not open the specified file name for write");
    }
    else
    {
      BAILMSG_IF(1, "Invalid option");
    }

    argi++;
  }

  // Validate combined parameter values

  if (server)
  {
    if (np == 0)
    {
      np = thread_count;
    }

    BAILMSG_IF((np < thread_count) && !reuseport, "-np value must be >= thread count unless -rup is specified");

    BAILMSG_IF((bp + np) > 65536, "-bp plus -np value must be <= 65536");
  }
  else
  {
    if (N == 0)
    {
      N = thread_count * 100;
    }

    if (P == 0)
    {
      P = N;
    }

    if (np == 0)
    {
      np = thread_count;
    }

    BAILMSG_IF(N < thread_count, "N must be >= thread count");
    BAILMSG_IF(P < thread_count, "P must be >= thread count");
    BAILMSG_IF(bcp != 0 && ncp < thread_count, "-ncp value must be >= thread count");

    BAILMSG_IF((bp + np) > 65536, "-bp plus -np value must be <= 65536");
    BAILMSG_IF(bcp != 0 && (bcp + ncp) > 65536, "-bcp plus -ncp value must be <= 65536");
  }

  int prev_bcp = bcp - 1;

  for (int r = 0; r < thread_count; r++)
  {
    param = malloc(ALIGN_UP(sizeof(*param), 128));
    BAIL_IF(param == NULL, -1);
    memset(param, 0, sizeof(*param));

    param->id = r;
    param->proc_index = affcount > 0 ? aff[r % affcount] : -1;
    param->thread_count = thread_count;
    param->local_address_specified = local_address_specified;
    param->xconnect = xconnect;
    param->xfer_mode = M;
    param->data_buffer_size = data_buffer_size;
    param->continuous_io_period_ms = continuous_io_period_ms;
    param->tcpkeepalive_sec = tcpkeepalive_sec;
    param->pollmode = (char)pollmode;
    param->reuseport = reuseport;
    param->disconnect_before_close = disconnect_before_close;
    param->abortive_close = abortive_close;
    param->donot_reconnect = donot_reconnect;

    memcpy(&param->local_address, &la, sizeof(sockaddr_inet));

    if (server)
    {
      param->local_port_start = bp;
      param->local_port_end = bp + np - 1;
    }
    else
    {
      memcpy(&param->remote_address, &ra, sizeof(sockaddr_inet));

      param->remote_port_start = bp;
      param->remote_port_end = bp + np - 1;

      if (bcp != 0)
      {
        param->local_port_start = prev_bcp + 1;
        param->local_port_end = param->local_port_start + (ncp / thread_count) - 1;
        if (r < (ncp % thread_count))
        {
          param->local_port_end += 1;
        }
        prev_bcp = param->local_port_end;
      }

      param->N = N / thread_count;
      if (r < (N % thread_count))
      {
        param->N += 1;
      }

      param->P = P / thread_count;
      if (r < (P % thread_count))
      {
        param->P += 1;
      }

      param->connection_duration_ms = D;
    }

    utilsw_list_insert_before(&param_list, &param->link);
  }

  BAILMSG_IF(prev_bcp > 65535, "Client port numbers exceed 65535!");

  init_console_input_thread();

  //
  // Start activity on all threads
  //

  if (delay_start_ms > 0)
  {
    utilsw_sleep(delay_start_ms);
  }

  if (outstream != NULL)
  {
    cps_output_stream = outstream;
    utilsw_set_output_stream(outstream);
  }

  init_connection_recording();

  unsigned long long t0, t1, t, dt;
  t0 = utilsw_get_millisec();

  if (skip_milliseconds == 0)
  {
    start_connection_recording();
  }

  list_entry = param_list.next;

  while (list_entry != &param_list)
  {
    param = (cps_param *)list_entry;
    list_entry = list_entry->next;

    utilsw_thread_t th;
    int rc = utilsw_thread_start(cps_thread_fn, param, &th);
    BAIL_IF(rc != SOCKWIZ_SUCCESS, rc);
  }

  //
  // Monitor and dump stats periodically
  //

  t1 = t0;

  cps_stat statA0 = {0};
  int skipped_warmup_time = !skip_milliseconds;
  signed long long rxbytes_at_warmup = 0;
  signed long long txbytes_at_warmup = 0;

  if (!silent)
  {
    if (display_brief == 0)
    {
      //                          1   2   3   4   5   6   7   8   9   10  11  12  13  14
      fprintf(cps_output_stream, "%9s %8s %6s %8s %8s %8s %8s %9s %9s %5s %7s %7s %7s %8s\n",
              /*1         2    3       4         5         6         7          8           9            10      11      12         13      14      */
              "T(sec)", "N", "Pend", "Failed", "IOFail", "Conn/s", "Close/s", "RXkbyte/s", "TXkbyte/s", "RT/i", "c0/i", "c0rtt/i", "cR/i", "cRrtt/i");
    }
  }

  for (;;)
  {
    utilsw_sleep(display_interval_ms);
    t = utilsw_get_millisec();

    cps_stat statA = {0};

    list_entry = param_list.next;

    int wrapped_around_ports = 0;

    while (list_entry != &param_list)
    {
      param = (cps_param *)list_entry;
      list_entry = list_entry->next;

      cps_stat *statThread = &param->stat;

      statA.open_count += statThread->open_count;
      statA.open_pending_count += statThread->open_pending_count;
      statA.open_failure_count += statThread->open_failure_count;
      statA.close_count += statThread->close_count;
      statA.iofailure_count += statThread->iofailure_count;
      statA.rx_byte_count += statThread->rx_byte_count;
      statA.tx_byte_count += statThread->tx_byte_count;
      statA.retrans_count += statThread->retrans_count;

      statA.rtt.rttsum += statThread->rtt.rttsum;
      statA.rtt.rttcount += statThread->rtt.rttcount;

      statA.rttRetrans.rttsum += statThread->rttRetrans.rttsum;
      statA.rttRetrans.rttcount += statThread->rttRetrans.rttcount;

      wrapped_around_ports += param->stat.wrapped_around_ports;
    }

    dt = t - t1;
    t1 = t;

    double cps = (double)(statA.open_count - statA0.open_count) * 1000 / dt;

    if (!silent)
    {
      unsigned long long c1 = statA.rtt.rttcount - statA0.rtt.rttcount;
      unsigned long long c2 = statA.rttRetrans.rttcount - statA0.rttRetrans.rttcount;

      if (display_brief == 0)
        //                          1     2     3     4     5     6     7     8     9     10    11    12    13    14
        fprintf(cps_output_stream, "%9.3f %8llu %6llu %8llu %8llu %8.1f %8.1f %9.1f %9.1f %5llu %7llu %7llu %7llu %8llu %s\n",
                /*1*/ (double)(t - t0) / 1000,                                      // time(s)
                /*2*/ statA.open_count - statA.close_count,                         // N (number of currently open connections)
                /*3*/ statA.open_pending_count,                                     // Pending connect count
                /*4*/ statA.open_failure_count,                                     // Failed connect or accept count (cumulative since T0)
                /*5*/ statA.iofailure_count,                                        // Failed send or receive count (cumulative since T0)
                /*6*/ cps,                                                          // open rate in the last interval
                /*7*/ (double)(statA.close_count - statA0.close_count) * 1000 / dt, // close rate in the last interval
                /*8*/ (double)(statA.rx_byte_count - statA0.rx_byte_count) / dt,    // rx byte rate in the last interval
                /*9*/ (double)(statA.tx_byte_count - statA0.tx_byte_count) / dt,    // tx byte rate in the last interval
                /*10*/ statA.retrans_count - statA0.retrans_count,                  // Retransmit count in the last interval
                /*11*/ c1,                                                          // open count with 0 retrans in the last interval
                /*12*/ c1 ? (statA.rtt.rttsum - statA0.rtt.rttsum) / c1 : 0,
                /*13*/ c2, // open count with retrans in the last interval
                /*14*/ c2 ? (statA.rttRetrans.rttsum - statA0.rttRetrans.rttsum) / c2 : 0,
                wrapped_around_ports ? "REP" : "");
      else if (display_brief == 1)
        fprintf(cps_output_stream, "%8llu %8.1f %7llu %8llu\n",
                statA.open_count - statA.close_count,
                cps,
                c1 ? (statA.rtt.rttsum - statA0.rtt.rttsum) / c1 : 0,
                c2 ? (statA.rttRetrans.rttsum - statA0.rttRetrans.rttsum) / c2 : 0);
      else
        fprintf(cps_output_stream, "%.1f\n", cps);
    }

    statA0 = statA;

    if (affcount == -1)
    {
      int res = track_rss_and_adjust_affinity(&param_list, cps);
      BAIL_IF(res < 0, res);
      if (res == 1)
      {
        affcount = 0;
      }
    }

    if (!skipped_warmup_time && (t - t0) >= skip_milliseconds)
    {
      skipped_warmup_time = 1;
      accumulate_rx_tx_byte_totals(&param_list, &rxbytes_at_warmup, &txbytes_at_warmup);
      start_connection_recording();
    }

    if (duration_ms != 0 && (t - t0) >= duration_ms)
    {
      stop_connection_recording();
      rxbytes_at_warmup *= -1;
      txbytes_at_warmup *= -1;
      accumulate_rx_tx_byte_totals(&param_list, &rxbytes_at_warmup, &txbytes_at_warmup);
      print_commandline(argc, argv);
      fprintf(cps_output_stream, "\n###RXGBPS %.2f\n", (double)(rxbytes_at_warmup * 8) / (double)1000000 / (double)(t - t0 - skip_milliseconds));
      fprintf(cps_output_stream, "###TXGBPS %.2f\n", (double)(txbytes_at_warmup * 8) / (double)1000000 / (double)(t - t0 - skip_milliseconds));
      summarize_connection_recording();
      if (outstream != NULL)
      {
        fclose(outstream);
      }

      exit(0);
    }
  }

exit:

  if (outstream != NULL)
  {
    fclose(outstream);
  }

  exit(-1);
}

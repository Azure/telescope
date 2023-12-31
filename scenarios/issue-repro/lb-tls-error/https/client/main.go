package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/sync/errgroup"
)

func main() {
	hostname := os.Getenv("SERVER_ADDRESS")
	if hostname == "" {
		fmt.Println("Please provide the load balancer URL or IP address.")
		return
	}
	port := os.Getenv("SERVER_PORT")
	protocol := "http"
	if port == "443" {
		protocol = "https"
	}
	url := fmt.Sprintf("%s://%s:%s/readyz", protocol, hostname, port)
	fmt.Println("Connecting to", url)

	durationMap := map[string]int{
		"error":     0,
		"<1s":       0,
		"1s-2s":     0,
		"2s-5s":     0,
		"5s-10s":    0,
		"10s-30s":   0,
		"30s-60s":   0,
		"60s-120s":  0,
		"120s-180s": 0,
		"180s-240s": 0,
		"240s-300s": 0,
		">300s":     0,
	}
	keys := []string{"<1s", "1s-2s", "2s-5s", "5s-10s", "10s-30s", "30s-60s", "60s-120s", "120s-180s", "180s-240s", "240s-300s", ">300s", "error"}

	var actualConns uint64
	totalConns, _ := strconv.ParseUint(os.Getenv("TOTAL_CONNECTIONS"), 10, 64)
	fmt.Printf("%v total connections to be established\n", totalConns)

	parallelConns, _ := strconv.ParseUint(os.Getenv("PARALLEL_CONNECTIONS"), 10, 64)
	fmt.Printf("%v parallel connections to be established\n", parallelConns)

	tlsHandshakeTimeout, _ := strconv.ParseInt(os.Getenv("TLS_HANDSHAKE_TIMEOUT"), 10, 64)
	fmt.Print("Set handshake timeout to ", tlsHandshakeTimeout, " seconds\n")

	disableKeepAlives, _ := strconv.ParseBool(os.Getenv("DISALBE_KEEP_ALIVES"))
	fmt.Print("Set disable keep alives to ", disableKeepAlives, "\n")

	var config *tls.Config
	if port == "443" {
		config = createTlsConfig()
	}

	// Create context with cancellation
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Create an errgroup with derived context
	eg, ctx := errgroup.WithContext(ctx)
	eg.SetLimit(int(parallelConns))

	mu := sync.Mutex{}

	for atomic.LoadUint64(&actualConns) < totalConns {
		eg.Go(func() error {
			duration, isErr := connect(config, url, time.Duration(tlsHandshakeTimeout)*time.Second, disableKeepAlives)

			mu.Lock()
			defer mu.Unlock()

			if isErr {
				durationMap["error"]++
			}

			switch {
			case duration >= 0 && duration < 1:
				durationMap["<1s"]++
			case duration >= 1 && duration < 2:
				durationMap["1s-2s"]++
			case duration >= 2 && duration < 5:
				durationMap["2s-5s"]++
			case duration >= 5 && duration < 10:
				durationMap["5s-10s"]++
			case duration >= 10 && duration < 30:
				durationMap["10s-30s"]++
			case duration >= 30 && duration < 60:
				durationMap["30s-60s"]++
			case duration >= 60 && duration < 120:
				durationMap["60s-120s"]++
			case duration >= 120 && duration < 180:
				durationMap["120s-180s"]++
			case duration >= 180 && duration < 240:
				durationMap["180s-240s"]++
			case duration >= 240 && duration < 300:
				durationMap["240s-300s"]++
			case duration >= 300:
				durationMap[">300s"]++
			}

			v := atomic.AddUint64(&actualConns, 1)
			if v%10000 == 0 {
				fmt.Printf("%v times %v\n", v, time.Now())
				fmt.Printf("Duration distribution:\n")
				for _, k := range keys {
					fmt.Printf("%v: %v\n", k, durationMap[k])
				}
			}
			return nil
		})
	}

	// Wait for all goroutines to complete or for an error to occur
	if err := eg.Wait(); err != nil {
		fmt.Printf("An error occurred: %v\n", err)
	}
}

func createTlsConfig() *tls.Config {
	// Load the server's certificate and private key files.
	cert, err := tls.LoadX509KeyPair("client.crt", "client.key")
	if err != nil {
		fmt.Println("Failed to load certificate and private key:", err)
		return nil
	}

	caCert, err := os.ReadFile("ca.crt")
	if err != nil {
		log.Fatalf("Error opening CA cert file, Error: %s", err)
	}
	caCertPool := x509.NewCertPool()
	caCertPool.AppendCertsFromPEM(caCert)

	// Create a TLS configuration with the loaded certificates.
	return &tls.Config{
		Certificates:       []tls.Certificate{cert},
		RootCAs:            caCertPool,
		InsecureSkipVerify: true,
	}
}

func connect(config *tls.Config, url string, tlsHandshakeTimeout time.Duration, disableKeepAlives bool) (float64, bool) {
	capturedConn := &capturedConn{}

	// Create a new HTTP transport with the custom TLS configuration.
	transport := &http.Transport{
		DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
			// Dial the remote server
			conn, err := net.DialTimeout(network, addr, 5*time.Second)
			if err != nil {
				return nil, err
			}

			// Wrap the connection to intercept Read and Write methods
			capturedConn.setConn(conn)
			return capturedConn, nil
		},
		TLSHandshakeTimeout: tlsHandshakeTimeout,
		DisableKeepAlives:   disableKeepAlives,
		TLSClientConfig:     config,
	}

	// Create a new HTTP client with the custom transport.
	client := &http.Client{
		Transport: transport,
	}

	// Create an HTTP request.
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		fmt.Printf("%v, Failed to create request: %v\n", time.Now(), err)
		return -1, true
	}

	// Send the request and get the response.
	startTime := time.Now()
	resp, err := client.Do(req)
	endTime := time.Now()
	duration := endTime.Sub(startTime).Seconds()

	if err != nil {
		fmt.Printf("%v, %v, Failed to send request with port %v and error: %v\n", endTime, startTime, capturedConn.getPort(), err)
		dumpResponse(resp)
		return duration, true
	}
	defer resp.Body.Close()

	if resp != nil && resp.StatusCode != 200 {
		dumpResponse(resp)
		return duration, true
	}

	return duration, false
}

func dumpResponse(resp *http.Response) {
	if resp == nil {
		return
	}
	fmt.Printf("%v, Response status: %v\n", time.Now(), resp.Status)
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		fmt.Printf("%v, Failed to read response body: %v\n", time.Now(), err)
		return
	}
	fmt.Printf("%v, Response body: %v\n", time.Now(), string(body))
}

// Custom net.Conn implementation that captures TCP packets
type capturedConn struct {
	net.Conn
	sync.Mutex
}

// Override Read method to capture incoming packets
func (c *capturedConn) Read(b []byte) (int, error) {
	n, err := c.Conn.Read(b)
	if err != nil {
		// Process captured packet here
		fmt.Printf("%s receive - remote: %s, local: %s\n", time.Now(), c.Conn.RemoteAddr(), c.Conn.LocalAddr())
	}
	return n, err
}

// Override Write method to capture outgoing packets
func (c *capturedConn) Write(b []byte) (int, error) {
	// Process captured packet here
	n, err := c.Conn.Write(b)
	if err != nil {
		fmt.Printf("%s sent - remote: %s, local: %s\n", time.Now(), c.Conn.RemoteAddr(), c.Conn.LocalAddr())
	}
	return n, err
}

func (c *capturedConn) setConn(conn net.Conn) {
	c.Lock()
	defer c.Unlock()
	c.Conn = conn
}

func (c *capturedConn) getPort() int {
	c.Lock()
	defer c.Unlock()
	if c.Conn == nil {
		return -1
	}
	return c.Conn.LocalAddr().(*net.TCPAddr).Port
}

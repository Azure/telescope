package main

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
	"golang.org/x/sync/errgroup"
)

var interrupt = make(chan os.Signal, 1)

func main() {
	hostname := os.Getenv("SERVER_ADDRESS")
	if hostname == "" {
		fmt.Println("Please provide the load balancer URL or IP address.")
		return
	}
	port := os.Getenv("SERVER_PORT")
	protocol := "wss"

	url := fmt.Sprintf("%s://%s:%s/ws", protocol, hostname, port)
	fmt.Println("Connecting to", url)

	durationMap := make(map[string]int)
	prematureClosureCount := 0

	var actualConns uint64
	totalConns, _ := strconv.ParseUint(os.Getenv("TOTAL_CONNECTIONS"), 10, 64)
	fmt.Printf("%v total connections to be established\n", totalConns)

	parallelConns, _ := strconv.ParseUint(os.Getenv("PARALLEL_CONNECTIONS"), 10, 64)
	fmt.Printf("%v parallel connections to be established\n", parallelConns)

	clientTimeout, _ := strconv.ParseInt(os.Getenv("CLIENT_TIMEOUT"), 10, 64)
	fmt.Print("Set client timeout to ", clientTimeout, " seconds\n")

	config := createTlsConfig()

	eg := &errgroup.Group{}
	eg.SetLimit(int(parallelConns))

	mu := sync.Mutex{}

	for {
		// Increment actualConns and check if it exceeds totalConns
		newActualConns := atomic.AddUint64(&actualConns, 1)
		if newActualConns > totalConns {
			break
		}

		// Launch a new goroutine to establish a WebSocket connection
		eg.Go(func() error {
			duration := connect(config, url, time.Duration(clientTimeout)*time.Second)

			mu.Lock()
			defer mu.Unlock()
			durationString := fmt.Sprintf("%.0f", duration)
			durationMap[durationString]++
			if duration < float64(clientTimeout) {
				prematureClosureCount++
			}

			return nil
		})
	}

	// Wait for all goroutines to complete or for an error to occur
	if err := eg.Wait(); err != nil {
		fmt.Printf("An error occurred: %v\n", err)
	}
	printDurationDistribution(durationMap, prematureClosureCount)
}

func createTlsConfig() *tls.Config {
	// Load the Client's certificate and private key files.
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

func connect(config *tls.Config, url string, websocketTimeout time.Duration) float64 {
	dialer := websocket.DefaultDialer
	dialer.TLSClientConfig = config
	dialer.HandshakeTimeout = 10 * time.Second
	conn, _, err := dialer.Dial(url, nil)
	if err != nil {
		log.Fatal("Error connecting to WebSocket server:", err)
	}
	defer conn.Close()

	startTime := time.Now()
	done := make(chan struct{})

	go func() {
		defer close(done)
		// Handle OS interrupts to gracefully close the connection.
		signal.Notify(interrupt, os.Interrupt)

		for {
			_, _, err := conn.ReadMessage()
			if err != nil {
				elapsedTime := time.Since(startTime).Seconds()
				if elapsedTime < websocketTimeout.Seconds() {
					fmt.Printf("Connection closed: %v with duration %v\n", err, elapsedTime)
				}
				return
			}
		}
	}()

	timeout := time.After(websocketTimeout)

	select {
	case <-done:
		return time.Since(startTime).Seconds()
	case <-timeout:
	case <-interrupt:
	}
	// Gracefully close the WebSocket connection
	err = conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
	if err != nil {
		log.Println("write close:", err)
	}

	return time.Since(startTime).Seconds()
}

func printDurationDistribution(durationMap map[string]int, prematureClosureCount int) {

	jsonData, err := json.Marshal(durationMap)
	if err != nil {
		log.Fatalf("Error marshaling JSON: %v", err)
	}

	fmt.Println(string(jsonData))
	fmt.Println("Total number of premature closures:", prematureClosureCount)
}

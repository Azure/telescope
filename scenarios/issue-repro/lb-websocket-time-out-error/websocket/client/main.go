package main

import (
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

	url := fmt.Sprintf("ws://%s:%s/ws", hostname, port)
	fmt.Println("Connecting to", url)

	durationMap := make(map[string]int)

	var actualConns uint64
	totalConns, _ := strconv.ParseUint(os.Getenv("TOTAL_CONNECTIONS"), 10, 64)
	fmt.Printf("%v total connections to be established\n", totalConns)

	parallelConns, _ := strconv.ParseUint(os.Getenv("PARALLEL_CONNECTIONS"), 10, 64)
	fmt.Printf("%v parallel connections to be established\n", parallelConns)

	clientTimeout, _ := strconv.ParseInt(os.Getenv("CLIENT_TIMEOUT"), 10, 64)
	fmt.Print("Set client timeout to ", clientTimeout, " seconds\n")

	eg := errgroup.Group{}
	eg.SetLimit(int(parallelConns))

	mu := sync.Mutex{}

	for atomic.LoadUint64(&actualConns) < totalConns {
		eg.Go(func() error {
			duration := connect(url, time.Duration(clientTimeout)*time.Second)

			mu.Lock()
			defer mu.Unlock()
			durationString := fmt.Sprintf("%.0f", duration)
			durationMap[durationString]++
			atomic.AddUint64(&actualConns, 1)
			return nil
		})
	}

	// Wait for all goroutines to complete or for an error to occur
	if err := eg.Wait(); err != nil {
		fmt.Printf("An error occurred: %v\n", err)
	}
	printDurationDistribution(durationMap)
}

func connect(url string, websocketTimeout time.Duration) float64 {
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
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
				fmt.Printf("Connection closed: %v with duration %v\n", err, time.Since(startTime).Seconds())
				return
			}
		}
	}()

	timeout := time.After(websocketTimeout)

	select {
	case <-done:
		return time.Since(startTime).Seconds()
	case <-timeout:
		fmt.Println("Timeout expired, closing connection...")
	case <-interrupt:
		fmt.Println("Interrupt received, closing connection...")
	}
	// Gracefully close the WebSocket connection
	err = conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
	if err != nil {
		log.Println("write close:", err)
	}

	return time.Since(startTime).Seconds()
}

func printDurationDistribution(durationMap map[string]int) {

	// Convert the map to JSON
	jsonData, err := json.Marshal(durationMap)
	if err != nil {
		log.Fatalf("Error marshaling JSON: %v", err)
	}

	fmt.Println(string(jsonData))
}

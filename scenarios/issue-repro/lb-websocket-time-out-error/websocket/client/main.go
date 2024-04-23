package main

import (
	"fmt"
	"log"
	"os"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
	"golang.org/x/sync/errgroup"
)

func main() {
	hostname := os.Getenv("SERVER_ADDRESS")
	if hostname == "" {
		fmt.Println("Please provide the load balancer URL or IP address.")
		return
	}
	port := os.Getenv("SERVER_PORT")

	url := fmt.Sprintf("ws://%s:%s/ws", hostname, port)
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

	connectionTimeout, _ := strconv.ParseInt(os.Getenv("TIMEOUT"), 10, 64)
	fmt.Print("Set websocket timeout to ", connectionTimeout, " seconds\n")

	eg := errgroup.Group{}
	eg.SetLimit(int(parallelConns))

	mu := sync.Mutex{}

	for atomic.LoadUint64(&actualConns) < totalConns {
		eg.Go(func() error {
			duration, isErr := connect(url, time.Duration(connectionTimeout)*time.Second)

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
			fmt.Println("Connection count:", v, time.Now())
			return nil
		})
	}

	// Wait for all goroutines to complete or for an error to occur
	if err := eg.Wait(); err != nil {
		fmt.Printf("An error occurred: %v\n", err)
	}
	printDurationDistribution(durationMap, keys)
}

func connect(url string, websocketTimeout time.Duration) (float64, bool) {
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		log.Fatal("Error connecting to WebSocket server:", err)
	}
	defer conn.Close()

	startTime := time.Now()
	done := make(chan struct{})

	go func() {
		defer close(done)
		for {
			_, _, err := conn.ReadMessage()
			if err != nil {
				fmt.Printf("Connection closed: %v\n", err)
				return
			}
		}
	}()
	timeout := time.After(websocketTimeout)

	select {
	case <-done:
		duration := time.Since(startTime)
		fmt.Printf("Connection duration: %v\n", duration)
		return duration.Seconds(), true

	case <-timeout:
		fmt.Printf("Connection timed out after %v seconds\n", time.Since(startTime).Seconds())
		err := conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
		if err != nil {
			log.Println("Error closing connection:", err)
			return 0, false
		}
		return websocketTimeout.Seconds(), true
	}
}

func printDurationDistribution(durationMap map[string]int, keys []string) {
	fmt.Println("Final duration distribution:")
	for _, k := range keys {
		fmt.Printf("%v: %v\n", k, durationMap[k])
	}
}

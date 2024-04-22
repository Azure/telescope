package main

import (
	"fmt"
	"log"
	"os"
	"os/signal"
	"time"

	"github.com/gorilla/websocket"
)

var interrupt = make(chan os.Signal, 1)

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Please provide the load balancer URL")
		return
	}

	// Replace the URL with your WebSocket server's URL.
	url := fmt.Sprintf("ws://%s:8080/ws", os.Args[1])
	fmt.Println("Connecting to", url)

	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		log.Fatal("Error connecting to WebSocket server:", err)
	}
	defer conn.Close()

	// Handle OS interrupts to gracefully close the connection.
	signal.Notify(interrupt, os.Interrupt)

	done := make(chan struct{})

	// Start a goroutine to read messages from the server.
	go func() {
		defer close(done)
		for {
			_, message, err := conn.ReadMessage()
			if err != nil {
				log.Println("Error reading from server:", err)
				return
			}
			fmt.Printf("Received: %s\n", message)
		}
	}()

	ticker := time.NewTicker(time.Second * 2)
	defer ticker.Stop()

	// Main loop to send messages and handle interrupts.
	for {
		select {
		case <-done:
			return
		case t := <-ticker.C:
			err := conn.WriteMessage(websocket.TextMessage, []byte(t.String()))
			if err != nil {
				log.Println("Error writing to server:", err)
				return
			}
		case <-interrupt:
			log.Println("Interrupt received, closing connection...")
			err := conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
			if err != nil {
				log.Println("Error closing connection:", err)
				return
			}
			select {
			case <-done:
			case <-time.After(time.Second):
			}
			return
		}
	}
}

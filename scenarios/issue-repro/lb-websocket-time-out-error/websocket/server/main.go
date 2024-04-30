package main

import (
	"fmt"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin: func(r *http.Request) bool {
		// Implement your logic here to check if the origin is allowed.
		// Return true if the origin is allowed, false otherwise.
		return true
	},
}

func handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		fmt.Println("Error upgrading connection:", err)
		return
	}
	defer conn.Close()

	// Set read and write deadlines
	serverTimeout, err := strconv.Atoi(os.Getenv("SERVER_TIMEOUT"))
	if err != nil {
		fmt.Println("Error converting SERVER_TIMEOUT to int:", err)
		return
	}
	fmt.Printf("Setting server timeout to %d seconds\n", serverTimeout)
	conn.SetReadDeadline(time.Now().Add(time.Duration(serverTimeout) * time.Second))
	conn.SetWriteDeadline(time.Now().Add(time.Duration(serverTimeout) * time.Second))

	clientAddr := conn.RemoteAddr().String()

	fmt.Printf("Client connected with IP address: %s\n", clientAddr)

	for {
		// Read message from the client
		_, _, err := conn.ReadMessage()
		if err != nil {
			fmt.Println("Read error:", err)
			break
		}
	}
}

func main() {
	port := os.Getenv("SERVER_PORT")
	http.HandleFunc("/ws", handleWebSocket)
	fmt.Println("WebSocket server listening on :", port)
	http.ListenAndServe(":"+port, nil)
}

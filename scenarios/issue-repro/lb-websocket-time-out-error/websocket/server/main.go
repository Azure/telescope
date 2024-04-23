package main

import (
	"fmt"
	"net"
	"net/http"
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

func handleConnection(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		fmt.Println("Error upgrading connection:", err)
		return
	}
	defer conn.Close()
	ip, err := getIPAddress()
	if err != nil {
		fmt.Println("Error getting IP address:", err)
		return
	}
	port := getPort()
	fmt.Printf("Client connected with IP address: %s:%d at %s\n", ip, port, time.Now())

	for {
		// Read message from the client
		_, msg, err := conn.ReadMessage()
		if err != nil {
			fmt.Println("Error reading message:", err)
			break
		}

		ip, err := getIPAddress()
		if err != nil {
			fmt.Println("Error getting IP address:", err)
			return
		}

		msg = []byte(fmt.Sprintf("%s from %s", msg, ip))

		fmt.Printf("Received: %s\n", msg)

		// if err := conn.WriteMessage(messageType, msg); err != nil {
		// 	fmt.Println("Error writing message:", err)
		// 	break
		// }
	}
}

func getPort() int {
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		return -1
	}
	defer conn.Close()

	return conn.LocalAddr().(*net.UDPAddr).Port
}

func getIPAddress() (string, error) {
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		return "", err
	}
	defer conn.Close()

	localAddr := conn.LocalAddr().(*net.UDPAddr)

	return localAddr.IP.String(), nil
}

func main() {
	http.HandleFunc("/ws", handleConnection)
	fmt.Println("WebSocket server listening on :8081")
	http.ListenAndServe(":8081", nil)
}

package main

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync"

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

func reader(conn *websocket.Conn) {
	for {
		_, _, err := conn.ReadMessage()
		if err != nil {
			fmt.Println("Read Error:", err)
			return
		}
	}
}

func handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		fmt.Println("Error upgrading connection:", err)
		return
	}
	defer conn.Close()

	clientAddr := conn.RemoteAddr().String()

	fmt.Printf("Client connected with IP address: %s\n", clientAddr)
	reader(conn)
}

func main() {
	port := os.Getenv("SERVER_PORT")

	// Serve the healthz endpoint.
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "ok\n")
	})

	var wg sync.WaitGroup
	wg.Add(2)

	httpServer := &http.Server{Addr: ":8080"}
	go func() {
		defer wg.Done()
		log.Println("Starting HTTP server on port 8080")
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("HTTP server error: %v", err)
		}
	}()

	// Load the custom CA certificate
	caCert, err := os.ReadFile("ca.crt")
	if err != nil {
		log.Fatalf("Error loading CA certificate: %v", err)
	}
	// Create a new certificate pool and add the CA certificate
	caCertPool := x509.NewCertPool()
	caCertPool.AppendCertsFromPEM(caCert)

	// Load the server certificate and key
	cert, err := tls.LoadX509KeyPair("server.crt", "server.key")
	if err != nil {
		log.Fatalf("Error loading server certificate and key: %v", err)
	}

	// Create a TLS config with the custom CA certificate pool and server certificate
	tlsConfig := &tls.Config{
		ClientCAs:  caCertPool,
		ClientAuth: tls.RequireAndVerifyClientCert,
		Certificates: []tls.Certificate{
			cert,
		},
	}
	httpsServer := &http.Server{
		Addr:      ":" + port,
		TLSConfig: tlsConfig,
	}

	go func() {
		defer wg.Done()
		http.HandleFunc("/ws", handleWebSocket)
		fmt.Println("Starting server on port:", port)
		if err = httpsServer.ListenAndServeTLS("", ""); err != nil {
			log.Fatal("Failed to start HTTPS server: ", err)
		}
	}()

	// Wait for both servers to finish.
	wg.Wait()
}

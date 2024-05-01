package main

import (
	"fmt"
	"os/exec"
	"time"
)

func main() {
	cmd := exec.Command("sleep", "10000")
	err := cmd.Start()
	if err != nil {
		fmt.Println(err)
		return
	}

	go cmd.Wait()
	time.Sleep(time.Second * 36000)
}

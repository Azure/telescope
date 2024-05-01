#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>

int main(int argc, char *argv[]) {
    // Create a child process
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <sleep_time>\n", argv[0]);
        return 1;
    }

    int sleep_time = atoi(argv[1]); // Convert command-line argument to integer
    printf("Sleep time: %d\n", sleep_time);

    pid_t child_pid = fork();
    if (child_pid == 0) {
        // Child process
        printf("Child process: %d\n", getpid());
        sleep(sleep_time); // Simulate some work
        exit(0); // Exit the child process
    } else {
        // Parent process
        printf("Parent process: %d\n", getpid());
        // Simulate some work
        sleep(5);
        // Do not wait for the child process to finish
        // This will cause the child process to become a zombie
        printf("Parent process exiting...\n");
        exit(1);
    }
    return 0;
}

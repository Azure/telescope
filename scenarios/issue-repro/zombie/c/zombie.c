#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>

int main(int argc, char *argv[])
{
    if (argc != 2)
    {
        fprintf(stderr, "Usage: %s <sleep_time>\n", argv[0]);
        return 1;
    }

    int sleep_time = atoi(argv[1]); // Convert command-line argument to integer
    printf("Sleep time: %d\n", sleep_time);

    pid_t child_pid;

    child_pid = fork();
    if (child_pid > 0)
    {
        printf("Child process: %d\n", getpid());
        sleep(sleep_time);
    }
    else
    {
        printf("Parent process: %d\n", getpid());
        exit(1);
    }
    return 1;
}
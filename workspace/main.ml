int arr[8];
int n;
int ignore;
int partition(int low, int high) {    
    int pivot;
    int i;
    int j;
    int t;
    pivot = arr[high];
    i = low - 1;
    j = low;
    while (j < high) {
        if (arr[j] < pivot) {
            i = i + 1;
            t = arr[i];
            arr[i] = arr[j];
            arr[j] = t;
        }
        j = j + 1;
    }
    t = arr[i + 1];
    arr[i + 1] = arr[high];
    arr[high] = t;
    return i + 1;
}

int quicksort(int low, int high) {
    int pi;
    if (low < high) {
        pi = partition(low, high);
        ignore = quicksort(low, pi - 1);
        ignore = quicksort(pi + 1, high);
    }
    return 0;
}

n = 8;
arr[0] = 64;
arr[1] = 34;
arr[2] = 25;
arr[3] = 12;
arr[4] = 22;
arr[5] = 11;
arr[6] = 90;
arr[7] = 5;

ignore = quicksort(0, n - 1);

n = 0;
while (n < 8) {
    print(arr[n]);
    n = n + 1;
}



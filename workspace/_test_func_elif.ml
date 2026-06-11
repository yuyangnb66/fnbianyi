int classify(int x) {
    if (x > 10) {
        return 3;
    } else if (x > 5) {
        return 2;
    } else if (x > 0) {
        return 1;
    } else {
        return 0;
    }
}

int main() {

int n;
print("test classify func:");
n = classify(12);
print(n);
n = classify(7);
print(n);
n = classify(3);
print(n);
n = classify(-1);
print(n);
return 0;
}



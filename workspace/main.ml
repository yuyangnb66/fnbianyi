int x;
int y;
string s;

x = 3 + 3;
y = 1;

if (x > 5) {
    print("x > 5");
} else if (x > 0) {
    print("x > 0");
    if (y == 1) {
        print("y == 1 (nested if)");
    }
} else if (x == 0) {
    print("x == 0");
} else {
    print("x < 0");
}

s = "hello";
if (s == "hello") {
    print("string compare ok");
} else if (s == "world") {
    print("world");
} else {
    print("other");
}











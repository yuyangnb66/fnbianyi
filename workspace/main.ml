int n;
int x;
int i;
int j;
int row_sum;
int total;
int t;
string line;

print("请输入行数 n 和每行个数 x（空格分隔）:");
input(n, x, "> ");

total = 0;
i = 0;
while (i < n) {
    print("请输入第",i+1,"行数据");
    
    input(line, "> ");

    row_sum = 0;
    j = 0;
    while (j < x) {
        t = getint(line, j);
        row_sum = row_sum + t;
        j = j + 1;
    }
    print("本行之和:");
    print(row_sum);

    total = total + row_sum;
    i = i + 1;
}

print("总和:");
print(total);


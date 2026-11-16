"""调试客户端：把命令行参数逐条发给 HyperMesh 常驻服务并打印结果。"""
import socket
import sys

PORT = 47999


def conn(port=PORT):
    s = socket.create_connection(("127.0.0.1", port), timeout=15)
    s.settimeout(300)
    return s, s.makefile("rw", encoding="utf-8", newline="\n")


def call(f, c):
    f.write(c.replace("\n", " ") + "\n")
    f.flush()
    return f.readline().rstrip("\n")


if __name__ == "__main__":
    s, f = conn()
    for c in sys.argv[1:]:
        print("> " + c)
        print("  " + call(f, c))

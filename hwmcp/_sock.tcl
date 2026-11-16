proc __hwmcp_read {chan} {
    if {[catch {gets $chan line} n]} { catch {close $chan}; return }
    if {$n < 0} { catch {close $chan}; return }
    set line [string trim $line]
    if {$line eq ""} { return }
    if {$line eq "__PING__"} { puts $chan "OK: pong"; flush $chan; return }
    if {$line eq "__EXIT__"} { puts $chan "OK: bye"; flush $chan; catch {close $chan}; exit }
    set rc [catch {uplevel #0 $line} res]
    regsub -all "\n" $res "\\n" res
    if {$rc} { puts $chan "ERR: $res" } else { puts $chan "OK: $res" }
    flush $chan
}
proc __hwmcp_serve {chan addr port} {
    fconfigure $chan -blocking 1 -buffering line
    fileevent $chan readable [list __hwmcp_read $chan]
}
set __port 0
if {[info exists env(HWMCP_PORT)]} { set __port $env(HWMCP_PORT) }
set __srv [socket -server __hwmcp_serve $__port]

# 端口由调用方通过 HWMCP_PORT 指定，这里只是回报实际端口，供人工排查。
# 必须能容错：HyperMesh 用 -tcl 且 stdout 被重定向时，Tcl 里可能没有 stdout
# 通道，直接 flush 会报 "can not find channel named stdout"，导致整个脚本中断、
# socket 服务建不起来，表现为客户端连接被立即关闭。
catch {
    puts "HWMCP_LISTEN [lindex [fconfigure $__srv -sockname] 2]"
    flush stdout
}

vwait forever

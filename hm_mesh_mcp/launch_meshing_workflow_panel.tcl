# -*- coding: utf-8 -*-
#
# HyperMesh offline meshing workflow launcher.
#
# Usage in HyperMesh Tcl command window:
#   source "E:/mcp/hypermesh-mcp-server/launch_meshing_workflow_panel.tcl"

namespace eval ::hm_mcp_launcher {
    variable project_dir [file normalize [file dirname [info script]]]
    variable python_exe "python"
    variable host "127.0.0.1"
    variable port 47881
    variable listener_retry_count 10
    variable last_listener_errors ""
    variable output_path [file normalize [file join $project_dir outputs full_mesh_from_panel.hm]]
    variable hm_step_path ""
    variable ansa_bridge_state_path [file normalize [file join $project_dir runs ansa_selected_step.json]]
    variable auto_listener 1
    variable continue_on_error 1

    variable drag_element_size_min 0.5
    variable drag_element_size_max 1.5
    variable drag_fit_tolerance_ratio 0.05
    variable drag_retry_count 2
    variable drag_aspect_guard 1

    variable tetra_element_size_min 1.5
    variable tetra_element_size_max 2.0
    variable tetra_min_element_size_min 0.4
    variable tetra_min_element_size_max 0.6
    variable tetra_max_deviation 0.1
    variable tetra_feature_angle 30
    variable tetra_growth_rate 1.23
    variable tetra_fit_tolerance_ratio 0.01
    variable tetra_chord_dev_degrade_delta 0.20
    variable tetra_target_vol_skew 0.70
    variable tetra_repair_vol_skew 0.99
    variable use_gear_tooth_refinement 1
    variable gear_tooth_element_size_min 1.2
    variable gear_tooth_element_size_max 1.6
    variable gear_tooth_min_element_size_min 0.2
    variable gear_tooth_min_element_size_max 0.3
    variable gear_tooth_feature_angle 15
    variable spin_section_element_size_min 0.20
    variable spin_section_element_size_max 1.50
    variable spin_density_min 60
    variable spin_density_max 160

    variable probe_timeout 180
    variable phase2_timeout 120
    variable drag_timeout 900
    variable spin_timeout 900
    variable tetra_timeout 1800
    variable save_timeout 300

    variable current_pid ""
    variable current_log ""
    variable current_stamp ""
    variable current_mode ""
    variable current_stop_file ""
    variable background_input_path ""
    variable last_log_size 0
    variable log_poll_ms 1200
    variable pid_check_ms 1800
    variable last_pid_check_ms 0
    variable log_max_lines 1200
    variable status_text "状态：未运行"
}

proc ::hm_mcp_launcher::last_nonempty_line {text} {
    set result ""
    foreach line [split $text "\n"] {
        set trimmed [string trim $line]
        if {$trimmed ne ""} {
            set result $trimmed
        }
    }
    return $result
}

proc ::hm_mcp_launcher::set_status {text} {
    variable status_text
    set status_text "状态：$text"
}

proc ::hm_mcp_launcher::panel_window {} {
    return .hm_mcp_meshing_launcher
}

proc ::hm_mcp_launcher::keep_panel_visible {} {
    variable current_pid
    set w [panel_window]
    if {![winfo exists $w]} {
        return
    }
    catch {
        wm attributes $w -topmost 1
    }
}

proc ::hm_mcp_launcher::append_log {text} {
    variable log_max_lines
    set widget .hm_mcp_meshing_launcher.root.logbox.text
    if {[winfo exists $widget]} {
        $widget configure -state normal
        $widget insert end $text
        set line_count [expr {int([$widget index end])}]
        if {$line_count > $log_max_lines} {
            set delete_to [expr {$line_count - $log_max_lines}]
            $widget delete 1.0 "$delete_to.0"
        }
        $widget see end
        $widget configure -state disabled
    }
}

proc ::hm_mcp_launcher::replace_log {text} {
    variable log_max_lines
    set widget .hm_mcp_meshing_launcher.root.logbox.text
    if {[winfo exists $widget]} {
        set lines [split $text "\n"]
        if {[llength $lines] > $log_max_lines} {
            set text [join [lrange $lines end-[expr {$log_max_lines - 1}] end] "\n"]
        }
        $widget configure -state normal
        $widget delete 1.0 end
        $widget insert end $text
        $widget see end
        $widget configure -state disabled
    }
}

proc ::hm_mcp_launcher::ensure_directories {} {
    variable project_dir
    file mkdir [file join $project_dir runs]
    file mkdir [file join $project_dir outputs]
}

proc ::hm_mcp_launcher::ensure_listener {} {
    variable project_dir
    variable python_exe
    variable port
    variable listener_retry_count
    variable last_listener_errors

    set old_pwd [pwd]
    set base_port $port
    set last_listener_errors ""
    set tried {}

    for {set offset 0} {$offset < $listener_retry_count} {incr offset} {
        set candidate [expr {$base_port + $offset}]
        if {[lsearch -exact $tried $candidate] >= 0} {
            continue
        }
        lappend tried $candidate
        set pycode [format {import hypermesh_mcp_server as hm; print(hm.create_gui_listener_tcl(port=%d)['script_path'])} $candidate]
        if {[catch {
            cd $project_dir
            set output [exec $python_exe -c $pycode]
        } err opts]} {
            append last_listener_errors "port=$candidate: create listener Tcl failed: $err\n"
            continue
        }

        set listener_path [last_nonempty_line $output]
        if {$listener_path eq ""} {
            append last_listener_errors "port=$candidate: Python 没有返回 listener Tcl 路径。\n"
            continue
        }
        set listener_path [file normalize $listener_path]
        if {![file exists $listener_path]} {
            append last_listener_errors "port=$candidate: listener Tcl 不存在：$listener_path\n"
            continue
        }
        if {[catch {source $listener_path} source_err source_opts]} {
            append last_listener_errors "port=$candidate: source listener failed: $source_err\n"
            continue
        }
        catch {cd $old_pwd}
        set port $candidate
        return $listener_path
    }

    catch {cd $old_pwd}
    error "所有自动连接端口都失败，已尝试：$tried\n$last_listener_errors"
}

proc ::hm_mcp_launcher::manual_connection_help_text {} {
    variable project_dir
    variable port
    variable listener_retry_count
    variable last_listener_errors
    set backup_port [expr {$port + $listener_retry_count}]
    set panel_path [file normalize [info script]]
    set ps_dir [file nativename $project_dir]
    set panel_tcl [string map {"\\" "/"} $panel_path]
    set py_cmd [format {python -c "import hypermesh_mcp_server as hm; print(hm.create_gui_listener_tcl(port=%d)['script_path'])"} $backup_port]
    return "\n手动建立连接方法：\n\n自动连接已经尝试从当前端口开始的一组备用端口。如果仍失败，建议不要继续使用当前端口 $port，先换新的备用端口 $backup_port。\n\n1. 在 PowerShell 中运行：\n   cd \"$ps_dir\"\n   $py_cmd\n\n2. 复制 PowerShell 输出的 Tcl 文件路径。\n\n3. 在 HyperMesh 的 Tcl 命令窗口中运行，注意把路径替换成上一步实际输出的路径：\n   source \"E:/mcp/hypermesh-mcp-server/runs/hypermesh_mcp_xxxxxx.tcl\"\n\n4. 告诉本面板后续使用同一个备用端口，在 HyperMesh Tcl 命令窗口中运行：\n   set ::hm_mcp_launcher::port $backup_port\n\n5. 如果只是重新打开本面板，也可以在 HyperMesh 中运行：\n   source \"$panel_tcl\"\n\n6. 连接成功后，回到本面板取消勾选“开始前自动建立/刷新 HyperMesh 连接”，再点击“开始划分”。\n\n自动连接失败详情：\n$last_listener_errors\n"
}

proc ::hm_mcp_launcher::make_stamp {} {
    set base [clock format [clock seconds] -format "%Y%m%d_%H%M%S"]
    set ms [format "%03d" [expr {[clock milliseconds] % 1000}]]
    set tail [format "%04d" [expr {int(rand() * 10000)}]]
    return "${base}_${ms}_${tail}"
}

proc ::hm_mcp_launcher::clamp_number {value low high fallback} {
    if {[catch {set number [expr {double($value)}]}]} {
        return $fallback
    }
    if {$number < $low} {
        return $low
    }
    if {$number > $high} {
        return $high
    }
    return $number
}

proc ::hm_mcp_launcher::normalize_pair {min_var max_var fallback_min fallback_max} {
    upvar 1 $min_var min_value
    upvar 1 $max_var max_value
    set min_value [clamp_number $min_value 0.000001 1000000 $fallback_min]
    set max_value [clamp_number $max_value 0.000001 1000000 $fallback_max]
    if {$min_value > $max_value} {
        set tmp $min_value
        set min_value $max_value
        set max_value $tmp
    }
}

proc ::hm_mcp_launcher::normalize_mesh_parameters {} {
    variable drag_element_size_min
    variable drag_element_size_max
    variable tetra_element_size_min
    variable tetra_element_size_max
    variable tetra_min_element_size_min
    variable tetra_min_element_size_max
    variable gear_tooth_element_size_min
    variable gear_tooth_element_size_max
    variable gear_tooth_min_element_size_min
    variable gear_tooth_min_element_size_max
    variable spin_section_element_size_min
    variable spin_section_element_size_max
    variable spin_density_min
    variable spin_density_max

    normalize_pair drag_element_size_min drag_element_size_max 0.5 1.5
    normalize_pair tetra_element_size_min tetra_element_size_max 1.5 2.0
    normalize_pair tetra_min_element_size_min tetra_min_element_size_max 0.4 0.6
    normalize_pair gear_tooth_element_size_min gear_tooth_element_size_max 1.2 1.6
    normalize_pair gear_tooth_min_element_size_min gear_tooth_min_element_size_max 0.2 0.3
    normalize_pair spin_section_element_size_min spin_section_element_size_max 0.20 1.50
    normalize_pair spin_density_min spin_density_max 60 160
    set spin_density_min [expr {int(round($spin_density_min))}]
    set spin_density_max [expr {int(round($spin_density_max))}]
    append_log "尺寸限制：drag=$drag_element_size_min..$drag_element_size_max, tetra目标=$tetra_element_size_min..$tetra_element_size_max, tetra最小=$tetra_min_element_size_min..$tetra_min_element_size_max, spin截面=$spin_section_element_size_min..$spin_section_element_size_max, spin份数=$spin_density_min..$spin_density_max\n"
}

proc ::hm_mcp_launcher::build_command {{mode full}} {
    variable project_dir
    variable python_exe
    variable host
    variable port
    variable output_path
    variable continue_on_error
    variable drag_element_size_min
    variable drag_element_size_max
    variable drag_fit_tolerance_ratio
    variable drag_retry_count
    variable drag_aspect_guard
    variable tetra_element_size_min
    variable tetra_element_size_max
    variable tetra_min_element_size_min
    variable tetra_min_element_size_max
    variable tetra_max_deviation
    variable tetra_feature_angle
    variable tetra_growth_rate
    variable tetra_fit_tolerance_ratio
    variable tetra_chord_dev_degrade_delta
    variable tetra_target_vol_skew
    variable tetra_repair_vol_skew
    variable use_gear_tooth_refinement
    variable gear_tooth_element_size_min
    variable gear_tooth_element_size_max
    variable gear_tooth_min_element_size_min
    variable gear_tooth_min_element_size_max
    variable gear_tooth_feature_angle
    variable spin_section_element_size_min
    variable spin_section_element_size_max
    variable spin_density_min
    variable spin_density_max
    variable probe_timeout
    variable phase2_timeout
    variable drag_timeout
    variable spin_timeout
    variable tetra_timeout
    variable save_timeout
    variable current_stamp
    variable background_input_path

    if {$mode eq "background"} {
        set runner [file join $project_dir run_full_meshing_workflow_batch.py]
    } else {
        set runner [file join $project_dir run_full_meshing_workflow.py]
    }
    set cmd [list $python_exe $runner \
        --host $host \
        --port $port \
        --output $output_path \
        --stamp $current_stamp \
        --probe-timeout $probe_timeout \
        --phase2-timeout $phase2_timeout \
        --drag-timeout $drag_timeout \
        --spin-timeout $spin_timeout \
        --tetra-timeout $tetra_timeout \
        --save-timeout $save_timeout \
        --drag-element-size $drag_element_size_max \
        --drag-element-size-min $drag_element_size_min \
        --drag-element-size-max $drag_element_size_max \
        --drag-fit-tolerance-ratio $drag_fit_tolerance_ratio \
        --drag-retry-count $drag_retry_count \
        --spin-section-element-size-min $spin_section_element_size_min \
        --spin-section-element-size-max $spin_section_element_size_max \
        --spin-density-min $spin_density_min \
        --spin-density-max $spin_density_max \
        --tetra-element-size $tetra_element_size_max \
        --tetra-element-size-min $tetra_element_size_min \
        --tetra-element-size-max $tetra_element_size_max \
        --tetra-min-element-size $tetra_min_element_size_max \
        --tetra-min-element-size-min $tetra_min_element_size_min \
        --tetra-min-element-size-max $tetra_min_element_size_max \
        --tetra-max-deviation $tetra_max_deviation \
        --tetra-feature-angle $tetra_feature_angle \
        --tetra-growth-rate $tetra_growth_rate \
        --tetra-fit-tolerance-ratio $tetra_fit_tolerance_ratio \
        --tetra-chord-dev-degrade-delta $tetra_chord_dev_degrade_delta \
        --tetra-target-vol-skew $tetra_target_vol_skew \
        --tetra-repair-vol-skew $tetra_repair_vol_skew \
        --gear-tooth-element-size $gear_tooth_element_size_max \
        --gear-tooth-element-size-min $gear_tooth_element_size_min \
        --gear-tooth-element-size-max $gear_tooth_element_size_max \
        --gear-tooth-min-element-size $gear_tooth_min_element_size_max \
        --gear-tooth-min-element-size-min $gear_tooth_min_element_size_min \
        --gear-tooth-min-element-size-max $gear_tooth_min_element_size_max \
        --gear-tooth-feature-angle $gear_tooth_feature_angle]
    if {$mode eq "background"} {
        set hmbatch_config [file normalize [file join $project_dir hypermesh_batch_path.txt]]
        if {[file exists $hmbatch_config]} {
            if {![catch {
                set fh [open $hmbatch_config r]
                fconfigure $fh -encoding utf-8
                set hmbatch_path [string trim [string map [list "\uFEFF" ""] [gets $fh]]]
                set hmbatch_path [string trim $hmbatch_path "\""]
                close $fh
            }]} {
                if {$hmbatch_path ne "" && [file exists $hmbatch_path]} {
                    lappend cmd --hmbatch $hmbatch_path
                }
            } else {
                catch {close $fh}
            }
        }
        lappend cmd --input $background_input_path
        variable current_stop_file
        if {$current_stop_file ne ""} {
            lappend cmd --stop-file $current_stop_file
        }
    }
    if {$continue_on_error} {
        lappend cmd --continue-on-error
    } else {
        lappend cmd --stop-on-error
    }
    if {$drag_aspect_guard} {
        lappend cmd --drag-aspect-guard
    }
    if {$use_gear_tooth_refinement} {
        lappend cmd --use-gear-tooth-refinement
    } else {
        lappend cmd --no-gear-tooth-refinement
    }
    if {$mode eq "gear_preview"} {
        lappend cmd --gear-tooth-preview-only
    } elseif {$mode eq "delete_gear_preview"} {
        lappend cmd --delete-gear-tooth-preview
    }
    return $cmd
}

proc ::hm_mcp_launcher::pid_running {pid} {
    if {$pid eq ""} {
        return 0
    }
    if {[catch {set out [exec tasklist /FI "PID eq $pid" /NH]}]} {
        return 0
    }
    if {[string first $pid $out] >= 0} {
        return 1
    }
    return 0
}

proc ::hm_mcp_launcher::save_background_snapshot {} {
    variable project_dir
    variable current_stamp
    variable background_input_path

    ensure_directories
    set snapshot [file normalize [file join $project_dir runs "panel_background_snapshot_$current_stamp.hm"]]
    set snapshot_tcl [string map {"\\" "/"} $snapshot]
    if {[catch {
        *writefile "$snapshot_tcl" 1
    } err opts]} {
        error "保存当前 HyperMesh 模型快照失败：$err"
    }
    if {![file exists $snapshot]} {
        error "保存当前 HyperMesh 模型快照失败：未生成 $snapshot"
    }
    set background_input_path $snapshot
    return $snapshot
}

proc ::hm_mcp_launcher::normalized_hm_step_path {} {
    variable hm_step_path
    set p [string trim $hm_step_path]
    if {$p eq ""} {
        return ""
    }
    set p [file normalize $p]
    set ext [string tolower [file extension $p]]
    if {[lsearch -exact {.stp .step .hm} $ext] < 0} {
        error "HM 输入文件必须是 .stp / .step / .hm：$p"
    }
    if {![file exists $p]} {
        error "HM 输入文件不存在：$p"
    }
    return $p
}

proc ::hm_mcp_launcher::read_new_log_data {} {
    variable current_log
    variable last_log_size

    if {$current_log eq "" || ![file exists $current_log]} {
        return ""
    }

    set size [file size $current_log]
    if {$size < $last_log_size} {
        set last_log_size 0
        replace_log ""
    }
    if {$size <= $last_log_size} {
        return ""
    }

    if {[catch {
        set fh [open $current_log r]
        fconfigure $fh -encoding utf-8
        seek $fh $last_log_size start
        set text [read $fh [expr {$size - $last_log_size}]]
        close $fh
    } read_err]} {
        catch {close $fh}
        return ""
    }
    set last_log_size $size
    return $text
}

proc ::hm_mcp_launcher::background_output_from_log {text} {
    set output ""
    foreach line [split $text "\n"] {
        if {[regexp {^Output:\s*(.+)$} $line -> path]} {
            set output [string trim $path]
        }
    }
    return $output
}

proc ::hm_mcp_launcher::parallel_hm_success_from_log {text} {
    return [regexp {(?m)^HM success:\s*True\s*$} $text]
}

proc ::hm_mcp_launcher::parallel_hm_usable_from_log {text} {
    if {[regexp {(?m)^HM usable:\s*True\s*$} $text]} {
        return 1
    }
    return [expr {[parallel_hm_success_from_log $text] || [parallel_hm_has_elements_from_log $text]}]
}

proc ::hm_mcp_launcher::parallel_severity_from_log {text} {
    set severity ""
    foreach line [split $text "\n"] {
        if {[regexp {^Parallel severity:\s*(.+)$} $line -> value]} {
            set severity [string trim $value]
        }
    }
    return $severity
}

proc ::hm_mcp_launcher::parallel_report_from_log {text} {
    set report ""
    foreach line [split $text "\n"] {
        if {[regexp {^Parallel report:\s*(.+)$} $line -> value]} {
            set report [string trim $value]
        }
    }
    return $report
}

proc ::hm_mcp_launcher::parallel_state_from_log {text} {
    set state ""
    foreach line [split $text "\n"] {
        if {[regexp {^Parallel state:\s*(.+)$} $line -> value]} {
            set state [string trim $value]
        }
    }
    return $state
}

proc ::hm_mcp_launcher::parallel_hm_has_elements_from_log {text} {
    foreach line [split $text "\n"] {
        if {[regexp {MCP_FINAL_COUNTS\s+elems=([0-9]+)} $line -> elems]} {
            if {[expr {int($elems)}] > 0} {
                return 1
            }
        }
    }
    return 0
}

proc ::hm_mcp_launcher::parallel_ansa_inp_from_log {text} {
    set inp ""
    foreach line [split $text "\n"] {
        if {[regexp {^ANSA INP:\s*(.+)$} $line -> path]} {
            set inp [string trim $path]
        }
    }
    return $inp
}

proc ::hm_mcp_launcher::path_is_ascii {value} {
    return [expr {[string length $value] == [string bytelength $value]}]
}

proc ::hm_mcp_launcher::safe_ansa_import_dir {} {
    variable project_dir
    if {[::hm_mcp_launcher::path_is_ascii $project_dir]} {
        return [file normalize [file join $project_dir runs ansa_import_safe]]
    }

    set volume [file volume $project_dir]
    if {$volume ne "" && [::hm_mcp_launcher::path_is_ascii $volume]} {
        set volume [string map {"\\" "/"} $volume]
        return [file normalize "${volume}/hm_ansa_exp_hmbatch_work"]
    }

    return [file normalize [file join [pwd] hm_ansa_exp_hmbatch_work]]
}

proc ::hm_mcp_launcher::stage_ansa_inp_for_hm_import {inp} {
    variable current_stamp

    if {[::hm_mcp_launcher::path_is_ascii $inp]} {
        return $inp
    }

    set safe_dir [::hm_mcp_launcher::safe_ansa_import_dir]
    file mkdir $safe_dir
    set staged [file normalize [file join $safe_dir "ansa_import_$current_stamp.inp"]]
    set idx 1
    while {[file exists $staged]} {
        set staged [file normalize [file join $safe_dir "ansa_import_${current_stamp}_$idx.inp"]]
        incr idx
    }
    file copy $inp $staged
    append_log "ANSA INP 路径含中文/非 ASCII，已复制到英文临时路径供 HyperMesh 导入：$staged\n"
    return $staged
}

proc ::hm_mcp_launcher::parallel_ansa_success_from_log {text} {
    return [regexp {(?m)^ANSA success:\s*True\s*$} $text]
}

proc ::hm_mcp_launcher::parallel_hm_final_elements_from_log {text} {
    set elems ""
    foreach line [split $text "\n"] {
        if {[regexp {^HM final elements:\s*([0-9]+)} $line -> value]} {
            set elems $value
        }
    }
    return $elems
}

proc ::hm_mcp_launcher::read_utf8_text_file {path} {
    set fh [open $path r]
    fconfigure $fh -encoding utf-8
    set text [read $fh]
    close $fh
    return $text
}

proc ::hm_mcp_launcher::wait_for_file {path {timeout_ms 3000}} {
    set deadline [expr {[clock milliseconds] + $timeout_ms}]
    while {[clock milliseconds] < $deadline} {
        if {[file exists $path]} {
            return 1
        }
        after 100
        catch {update}
    }
    return [file exists $path]
}

proc ::hm_mcp_launcher::cleanup_assemblies_only {{source_label ""}} {
    set removed 0
    foreach entity_type {assems assemblies} {
        set ids {}
        if {[catch {
            *createmark $entity_type 1 all
            set ids [hm_getmark $entity_type 1]
        }]} {
            continue
        }
        set n [llength $ids]
        if {$n <= 0} {
            continue
        }
        catch {hm_answernext yes}
        if {[catch {
            *deletemark $entity_type 1
        } err]} {
            append_log "Assembly 层级清理跳过：$err\n"
            continue
        }
        incr removed $n
    }
    if {$removed > 0} {
        if {$source_label eq ""} {
            append_log "已清理 Assembly 层级：$removed 个；Components/网格保留。\n"
        } else {
            append_log "$source_label 已清理 Assembly 层级：$removed 个；Components/网格保留。\n"
        }
    }
    return $removed
}

proc ::hm_mcp_launcher::open_background_output_if_ready {log_text} {
    set output [background_output_from_log $log_text]
    if {$output eq ""} {
        append_log "后台结果尚未写出 Output 路径，跳过自动打开。\n"
        return 0
    }
    set output [file normalize $output]
    if {![::hm_mcp_launcher::wait_for_file $output 5000]} {
        append_log "后台输出文件不存在，跳过自动打开：$output\n"
        return 0
    }
    set output_tcl [string map {"\\" "/"} $output]
    append_log "后台划分结束，正在当前 HyperMesh 界面打开结果：$output\n"
    if {[catch {
        catch {hm_answernext yes}
        *readfile "$output_tcl"
        ::hm_mcp_launcher::cleanup_assemblies_only "HM 后台结果"
        catch {*fit}
    } err]} {
        append_log "自动打开后台结果失败：$err\n"
        return 0
    }
    append_log "已在当前 HyperMesh 界面打开后台划分结果。\n"
    return 1
}

proc ::hm_mcp_launcher::import_ansa_inp_if_ready {log_text} {
    set inp [parallel_ansa_inp_from_log $log_text]
    if {$inp eq ""} {
        append_log "并行结果中未找到 ANSA INP 路径，跳过 ANSA 网格导入。\n"
        return 0
    }
    set inp [file normalize $inp]
    if {![::hm_mcp_launcher::wait_for_file $inp 5000]} {
        append_log "ANSA INP 文件不存在，跳过导入：$inp\n"
        return 0
    }
    if {[catch {set import_inp [::hm_mcp_launcher::stage_ansa_inp_for_hm_import $inp]} err]} {
        append_log "准备 ANSA INP 英文导入路径失败：$err\n"
        return 0
    }
    set inp_tcl [string map {"\\" "/"} $import_inp]
    append_log "正在导入 ANSA INP 网格到当前 HyperMesh：$import_inp\n"
    if {[catch {
        catch {hm_answernext yes}
        *feinputpreserveincludefiles
        *createstringarray 8 "Abaqus " "Standard3D " "LOADCOLS_DISPLAY_SKIP " "SYSTCOLS_DISPLAY_SKIP " \
            "CONTACTSURF_DISPLAY_SKIP " "IMPORT_MATERIAL_METADATA " "ANSA_PARALLEL_IMPORT " ""
        *feinputwithdata2 "\#abaqus\\abaqus" "$inp_tcl" 0 0 0 0 0 1 8 1 0
        *createmark elems 1 all
        set elem_count [llength [hm_getmark elems 1]]
        *createmark comps 1 all
        set comp_count [llength [hm_getmark comps 1]]
        catch {*fit}
    } err]} {
        append_log "导入 ANSA INP 失败：$err\n"
        return 0
    }
    append_log "已导入 ANSA INP：当前 elems=$elem_count comps=$comp_count。\n"
    return 1
}

proc ::hm_mcp_launcher::open_parallel_outputs_if_ready {log_text} {
    set opened_hm 0
    if {[parallel_hm_success_from_log $log_text]} {
        set opened_hm [open_background_output_if_ready $log_text]
    } elseif {[parallel_hm_has_elements_from_log $log_text]} {
        append_log "HM 后台结果有网格单元但存在警告/退回，仍然打开 HM 输出用于合并查看。\n"
        set opened_hm [open_background_output_if_ready $log_text]
    } else {
        append_log "HM 后台结果未成功或零网格，跳过自动打开 HM 输出。\n"
    }
    set imported_ansa [import_ansa_inp_if_ready $log_text]
    if {$opened_hm || $imported_ansa} {
        set state [parallel_state_from_log $log_text]
        if {$state ne ""} {
            append_log "并行状态文件：$state\n"
        }
        set report [parallel_report_from_log $log_text]
        if {$report ne ""} {
            append_log "并行划分报告：$report\n"
        }
        return 1
    }
    return 0
}

proc ::hm_mcp_launcher::show_background_popup_summary_if_needed {} {
    variable project_dir
    variable current_stamp

    if {$current_stamp eq ""} {
        return 0
    }
    set popup_path [file normalize [file join $project_dir runs "workflow_popup_summary_$current_stamp.txt"]]
    if {![file exists $popup_path]} {
        append_log "未找到后台弹窗摘要文件，跳过质量提示弹窗：$popup_path\n"
        return 0
    }
    if {[catch {
        set fh [open $popup_path r]
        fconfigure $fh -encoding utf-8
        set text [read $fh]
        close $fh
    } err]} {
        catch {close $fh}
        append_log "读取后台弹窗摘要失败：$err\n"
        return 0
    }
    if {[string first "没有实体退回到 2D 面网格" $text] >= 0} {
        append_log "后台弹窗摘要未发现 2D 回退。\n"
        return 0
    }
    append_log "正在显示后台质量提示弹窗：$popup_path\n"
    catch {
        tk_messageBox -type ok -icon warning -title "网格退回提醒" -message $text
    }
    return 1
}

proc ::hm_mcp_launcher::show_parallel_popup_summary_if_needed {log_text} {
    variable project_dir
    variable current_stamp

    if {$current_stamp eq ""} {
        return 0
    }

    set hm_ok [parallel_hm_usable_from_log $log_text]
    set ansa_ok [parallel_ansa_success_from_log $log_text]
    set severity [parallel_severity_from_log $log_text]
    set hm_elems [parallel_hm_final_elements_from_log $log_text]
    set report_path [parallel_report_from_log $log_text]

    set lines {}
    set icon "info"
    if {$hm_ok && $ansa_ok && ($severity eq "ok" || $severity eq "")} {
        lappend lines "全部划分成功。"
    } elseif {$hm_ok && $ansa_ok} {
        set icon "warning"
        lappend lines "HM 与 ANSA 都生成了可用结果，但存在警告。"
    } elseif {$hm_ok && !$ansa_ok} {
        set icon "warning"
        lappend lines "部分完成：HM 生成了可用网格，ANSA 未生成可用 INP。"
    } elseif {!$hm_ok && $ansa_ok} {
        set icon "warning"
        lappend lines "部分完成：ANSA 生成了可用 INP，HM 未生成可用网格。"
    } else {
        set icon "error"
        lappend lines "HM 与 ANSA 都没有生成可合并的可用结果。"
    }

    lappend lines ""
    if {$hm_ok} {
        set hm_text "是"
    } else {
        set hm_text "否"
    }
    if {$ansa_ok} {
        set ansa_text "是"
    } else {
        set ansa_text "否"
    }

    if {$hm_elems ne ""} {
        lappend lines "HM：可用=$hm_text，单元数=$hm_elems"
    } else {
        lappend lines "HM：可用=$hm_text"
    }
    set hm_popup_path [file normalize [file join $project_dir runs "workflow_popup_summary_$current_stamp.txt"]]
    if {[file exists $hm_popup_path]} {
        if {![catch {set hm_popup [read_utf8_text_file $hm_popup_path]} err]} {
            if {[string first "没有实体退回到 2D 面网格" $hm_popup] < 0} {
                lappend lines ""
                lappend lines "HM 质量提示："
                lappend lines [string trim $hm_popup]
                if {$icon eq "info"} {
                    set icon "warning"
                }
            }
        } else {
            append_log "读取 HM 后台弹窗摘要失败：$err\n"
        }
    }

    set ansa_part_count ""
    set ansa_total_count ""
    set ansa_skipped_count 0
    set ansa_failed_count 0
    set ansa_message ""
    set ansa_issue_lines {}
    if {$report_path ne "" && [file exists $report_path]} {
        if {![catch {set report_text [read_utf8_text_file $report_path]} err]} {
            set collect_mode ""
            foreach line [split $report_text "\n"] {
                if {[regexp {^  message:\s*(.*)$} $line -> value]} {
                    set ansa_message [string trim $value]
                } elseif {[regexp {^  parts:\s*meshed=([^ ]+)\s*/\s*total=([^ ]+)} $line -> meshed total]} {
                    set ansa_part_count [string trim $meshed]
                    set ansa_total_count [string trim $total]
                } elseif {[regexp {^  skipped_part_count:\s*([0-9]+)} $line -> value]} {
                    set ansa_skipped_count $value
                } elseif {[regexp {^  failed_part_count:\s*([0-9]+)} $line -> value]} {
                    set ansa_failed_count $value
                } elseif {[regexp {^  skipped_parts:} $line]} {
                    set collect_mode "未划分"
                } elseif {[regexp {^  failed_parts:} $line]} {
                    set collect_mode "划分失败"
                } elseif {$collect_mode ne "" && [regexp {^    -\s*(.+)$} $line -> value]} {
                    if {[llength $ansa_issue_lines] < 12} {
                        lappend ansa_issue_lines "$collect_mode：$value"
                    }
                } elseif {[string index $line 0] eq "\[" || [regexp {^  [a-zA-Z_]+:} $line]} {
                    set collect_mode ""
                }
            }
            append_log "并行详细报告：$report_path\n"
        } else {
            append_log "读取并行报告失败：$err\n"
        }
    }

    lappend lines ""
    if {$ansa_ok && [expr {int($ansa_skipped_count)}] == 0 && [expr {int($ansa_failed_count)}] == 0} {
        if {$ansa_part_count ne "" && $ansa_total_count ne ""} {
            lappend lines "ANSA：全部划分成功（$ansa_part_count / $ansa_total_count 个部件）。"
        } else {
            lappend lines "ANSA：全部划分成功。"
        }
    } elseif {$ansa_ok} {
        set icon "warning"
        lappend lines "ANSA：部分部件未划分成功。"
        lappend lines "未划分：$ansa_skipped_count 个；划分失败：$ansa_failed_count 个。"
        if {[llength $ansa_issue_lines] > 0} {
            lappend lines "涉及部件："
            foreach item $ansa_issue_lines {
                lappend lines "  - $item"
            }
            set total_issue_count [expr {int($ansa_skipped_count) + int($ansa_failed_count)}]
            if {$total_issue_count > [llength $ansa_issue_lines]} {
                lappend lines "  - ... 其余部件请看运行日志/并行报告。"
            }
        } elseif {$ansa_message ne ""} {
            lappend lines "ANSA 信息：$ansa_message"
        }
    } else {
        set icon "warning"
        if {$ansa_message ne ""} {
            lappend lines "ANSA：未全部划分成功。$ansa_message"
        } else {
            lappend lines "ANSA：未全部划分成功。"
        }
    }

    set popup_path [file normalize [file join $project_dir runs "parallel_popup_summary_$current_stamp.txt"]]
    if {![catch {
        set fh [open $popup_path w]
        fconfigure $fh -encoding utf-8
        puts $fh [join $lines "\n"]
        close $fh
    } err]} {
        append_log "正在显示 HM+ANSA 并行结果弹窗：$popup_path\n"
    } else {
        catch {close $fh}
        append_log "写入 HM+ANSA 并行结果弹窗摘要失败：$err\n"
    }

    catch {
        tk_messageBox -type ok -icon $icon -title "HM+ANSA 同时划分结果" -message [join $lines "\n"]
    }
    return 1
}

proc ::hm_mcp_launcher::cmd_quote_arg {value} {
    set text [file nativename $value]
    set text [string map {"%" "%%" "\"" "\"\""} $text]
    return "\"$text\""
}

proc ::hm_mcp_launcher::vbs_quote {value} {
    return "\"[string map {"\"" "\"\""} $value]\""
}

proc ::hm_mcp_launcher::write_argv_file {path argv_list} {
    set fh [open $path w]
    fconfigure $fh -encoding utf-8
    foreach arg $argv_list {
        puts $fh $arg
    }
    close $fh
}

proc ::hm_mcp_launcher::start_hidden_logged_process {cmd log_path} {
    variable project_dir
    variable current_stamp

    if {[llength [info commands puts]] == 0} {
        error "Tcl puts command is unavailable, cannot create hidden launcher files"
    }

    set cmd_path [file normalize [file join $project_dir runs "panel_hidden_launch_$current_stamp.cmd"]]
    set vbs_path [file normalize [file join $project_dir runs "panel_hidden_launch_$current_stamp.vbs"]]

    set quoted_args {}
    foreach arg $cmd {
        lappend quoted_args [cmd_quote_arg $arg]
    }
    set command_line [join $quoted_args " "]
    set log_arg [cmd_quote_arg $log_path]
    set fh [open $cmd_path w]
    fconfigure $fh -encoding utf-8
    puts $fh "@echo off"
    puts $fh "cd /d [cmd_quote_arg $project_dir]"
    puts $fh "$command_line > $log_arg 2>&1"
    puts $fh "exit /b %ERRORLEVEL%"
    close $fh

    set cmd_native [file nativename $cmd_path]
    set run_command "%ComSpec% /D /C \"\"$cmd_native\"\""
    set fh [open $vbs_path w]
    fconfigure $fh -encoding utf-8
    puts $fh "Set shell = CreateObject(\"WScript.Shell\")"
    puts $fh "code = shell.Run([vbs_quote $run_command], 0, True)"
    puts $fh "WScript.Quit code"
    close $fh

    if {![catch {
        set pids [exec wscript.exe [file nativename $vbs_path] &]
    } hidden_err]} {
        return $pids
    }

    return [exec {*}$cmd > $log_path 2>@1 &]
}

proc ::hm_mcp_launcher::poll_log {} {
    variable current_pid
    variable current_log
    variable current_mode
    variable current_stamp
    variable log_poll_ms
    variable pid_check_ms
    variable last_pid_check_ms

    set new_text [read_new_log_data]
    if {$new_text ne ""} {
        append_log $new_text
    }

    if {$current_pid ne ""} {
        set now_ms [clock milliseconds]
        if {$last_pid_check_ms == 0 || ($now_ms - $last_pid_check_ms) >= $pid_check_ms} {
            set last_pid_check_ms $now_ms
            set still_running [pid_running $current_pid]
        } else {
            set still_running 1
        }
        if {$still_running} {
            after $log_poll_ms ::hm_mcp_launcher::poll_log
        } else {
            set current_pid ""
            keep_panel_visible
            if {$current_log ne "" && [file exists $current_log]} {
                set final_text [read_new_log_data]
                if {$final_text ne ""} {
                    append_log $final_text
                }
                set fh [open $current_log r]
                fconfigure $fh -encoding utf-8
                set text [read $fh]
                close $fh
                if {$current_mode eq "background"} {
                    open_background_output_if_ready $text
                    show_background_popup_summary_if_needed
                } elseif {$current_mode eq "parallel"} {
                    open_parallel_outputs_if_ready $text
                    show_parallel_popup_summary_if_needed $text
                }
                if {$current_mode eq "parallel"} {
                    set severity [parallel_severity_from_log $text]
                    if {$severity eq "ok"} {
                        set_status "完成合并"
                    } elseif {$severity eq "warning"} {
                        set_status "完成合并，存在警告"
                    } elseif {$severity eq "partial"} {
                        set_status "部分完成，已导入可用结果"
                    } elseif {$severity eq "stopped"} {
                        set_status "已停止"
                    } elseif {$severity eq "failed"} {
                        set_status "并行划分失败，请查看日志"
                    } elseif {[parallel_hm_usable_from_log $text] && [regexp {(?m)^ANSA success:\s*True\s*$} $text]} {
                        set_status "完成合并，存在警告"
                    } elseif {[parallel_hm_usable_from_log $text]} {
                        set_status "HM 已完成，ANSA 侧失败或未输出"
                    } elseif {[regexp {(?m)^ANSA success:\s*True\s*$} $text]} {
                        set_status "ANSA 已完成，HM 侧失败或零网格"
                    } else {
                        set_status "流程结束，但存在失败或警告，请查看日志"
                    }
                } elseif {[regexp {(?m)^Success:\s*True\s*$} $text]} {
                    set_status "完成划分"
                } elseif {$current_mode eq "background" && [parallel_hm_has_elements_from_log $text]} {
                    set_status "完成划分，存在警告"
                } else {
                    set_status "流程结束，但存在失败或警告，请查看日志"
                }
            } else {
                set_status "流程结束，但未找到日志"
            }
        }
    }
}

proc ::hm_mcp_launcher::start_workflow {{mode full}} {
    variable project_dir
    variable auto_listener
    variable port
    variable current_pid
    variable current_log
    variable current_stamp
    variable current_mode
    variable current_stop_file
    variable last_log_size
    variable last_pid_check_ms

    if {$current_pid ne ""} {
        set_status "当前已有流程在运行"
        append_log "\n当前已有后台流程在运行，先停止或等待它结束。\n"
        return
    }

    ensure_directories
    set current_stamp [make_stamp]
    set current_mode $mode
    set current_stop_file ""
    if {$mode eq "gear_preview"} {
        set current_log [file normalize [file join $project_dir runs "panel_gear_tooth_preview_$current_stamp.log"]]
    } elseif {$mode eq "delete_gear_preview"} {
        set current_log [file normalize [file join $project_dir runs "panel_delete_gear_tooth_preview_$current_stamp.log"]]
    } elseif {$mode eq "background"} {
        set current_log [file normalize [file join $project_dir runs "panel_background_workflow_$current_stamp.log"]]
        set current_stop_file [file normalize [file join $project_dir runs "stop_background_$current_stamp.flag"]]
        if {[file exists $current_stop_file]} {
            catch {file delete $current_stop_file}
        }
    } else {
        set current_log [file normalize [file join $project_dir runs "panel_workflow_$current_stamp.log"]]
    }
    set last_log_size 0
    set last_pid_check_ms 0
    replace_log ""
    normalize_mesh_parameters

    if {$mode eq "background"} {
        if {[catch {set picked_background_input [normalized_hm_step_path]} err]} {
            set_status "HM STEP 输入无效"
            append_log "后台划分无法启动：$err\n"
            tk_messageBox -icon warning -title "HM STEP 输入无效" -message $err
            return
        }
        if {$picked_background_input ne ""} {
            variable background_input_path
            set background_input_path $picked_background_input
            append_log "后台划分使用 HM 输入文件：$background_input_path\n"
        } else {
            set_status "正在保存当前模型快照"
            append_log "HM STEP 为空，正在保存当前 HyperMesh 模型为后台划分快照...\n"
            if {[catch {set snapshot_path [save_background_snapshot]} err]} {
                set_status "后台快照保存失败"
                append_log "后台划分无法启动：$err\n"
                tk_messageBox -icon warning -title "HM 没有可划分模型" -message "HM 面板未选择 STEP，且当前 HyperMesh 模型快照保存失败。\n\n请先在 HM 面板选择 HM STEP，或在 HyperMesh 中导入模型。\n\n$err"
                return
            }
            append_log "后台划分快照：$snapshot_path\n"
        }
    } elseif {$auto_listener} {
        set_status "正在建立 HyperMesh 连接"
        append_log "正在建立 HyperMesh 连接...\n"
        if {[catch {set listener_path [ensure_listener]} err]} {
            set_status "连接失败"
            append_log "自动建立连接失败：$err\n"
            append_log [manual_connection_help_text]
            return
        }
        append_log "连接成功：$listener_path\n当前端口：$port\n"
    }

    set cmd [build_command $mode]
    set old_pwd [pwd]
    set_status "正在启动后台划分流程"
    append_log "正在启动后台划分流程...\n日志文件：$current_log\n\n"
    if {[catch {
        cd $project_dir
        set pids [start_hidden_logged_process $cmd $current_log]
    } err opts]} {
        catch {cd $old_pwd}
        set_status "启动失败"
        append_log "无法启动离线划分流程：$err\n"
        return
    }
    catch {cd $old_pwd}

    set current_pid [lindex $pids 0]
    set_status "运行中，PID=$current_pid"
    append_log "已开始运行，PID=$current_pid。\n\n"
    keep_panel_visible
    after 1000 ::hm_mcp_launcher::poll_log
}

proc ::hm_mcp_launcher::stop_workflow {} {
    variable current_pid
    variable current_log
    variable current_mode
    variable current_stop_file
    variable log_poll_ms

    if {$current_pid eq ""} {
        set_status "当前没有运行中的流程"
        append_log "\n当前没有由这个面板启动的后台 Python 流程。\n"
        keep_panel_visible
        return
    }

    set pid $current_pid
    if {$current_mode eq "background" || $current_mode eq "parallel"} {
        if {$current_stop_file eq ""} {
            variable project_dir
            variable current_stamp
            if {$current_mode eq "parallel"} {
                set current_stop_file [file normalize [file join $project_dir runs "stop_parallel_$current_stamp.flag"]]
            } else {
                set current_stop_file [file normalize [file join $project_dir runs "stop_background_$current_stamp.flag"]]
            }
        }
        if {$current_mode eq "parallel"} {
            set_status "已请求停止 HM+ANSA，等待协调器收尾"
            append_log "\n正在请求 HM+ANSA 同时划分停止 PID=$pid ...\n"
        } else {
            set_status "已请求停止，等待当前阶段保存"
            append_log "\n正在请求后台划分停止 PID=$pid ...\n"
        }
        set stop_text "stop requested at [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}] for PID=$pid"
        if {[catch {
            set fh [open $current_stop_file w]
            fconfigure $fh -encoding utf-8
            if {[llength [info commands puts]] > 0} {
                puts $fh $stop_text
            } elseif {[llength [info commands chan]] > 0} {
                chan puts $fh $stop_text
            } else {
                error "Tcl puts command is unavailable"
            }
            close $fh
        } err]} {
            catch {close $fh}
            if {[catch {exec cmd.exe /D /C echo $stop_text > $current_stop_file} err2]} {
                set_status "停止请求写入失败"
                append_log "停止请求写入失败：$err\n兜底写入也失败：$err2\n日志：$current_log\n"
            } else {
                append_log "已写入停止请求：$current_stop_file\n"
            }
        } else {
            if {$current_mode eq "parallel"} {
                append_log "已写入停止请求：$current_stop_file\n协调器会同时停止 HM 后台和 ANSA no-gui 子进程。\n"
            } else {
                append_log "已写入停止请求：$current_stop_file\n当前 hmbatch 阶段结束后会保存输出 HM，然后本面板会自动打开该 HM。\n"
            }
        }
        after $log_poll_ms ::hm_mcp_launcher::poll_log
    } else {
        set current_pid ""
        set_status "正在停止 PID=$pid"
        append_log "\n正在停止后台 Python 流程 PID=$pid ...\n"
        if {[catch {exec taskkill /PID $pid /T /F} err]} {
            set_status "停止命令已执行，请检查日志"
            append_log "停止命令返回：$err\n如果 HyperMesh 已经开始执行一段很长的 Tcl，可能会完成当前命令后才停下来。\n日志：$current_log\n"
        } else {
            set_status "已停止后台 Python 流程"
            append_log "后台 Python 流程已停止。如果 HyperMesh 正在执行已提交的 Tcl，可能还会短暂继续当前命令。\n"
        }
    }
    keep_panel_visible
}

proc ::hm_mcp_launcher::browse_output_path {} {
    variable output_path
    set picked [tk_getSaveFile -title "选择最终 HM 文件" -defaultextension ".hm" -filetypes {{"HyperMesh files" {.hm}} {"All files" {*}}}]
    if {$picked ne ""} {
        set output_path [file normalize $picked]
    }
}

proc ::hm_mcp_launcher::browse_hm_step_path {} {
    variable hm_step_path
    set picked [tk_getOpenFile -title "选择 HM 侧输入模型" -filetypes {{"STEP/HM files" {.stp .step .hm}} {"STEP files" {.stp .step}} {"HyperMesh files" {.hm}} {"All files" {*}}}]
    if {$picked ne ""} {
        set hm_step_path [file normalize $picked]
        refresh_hm_step_display
    }
}

proc ::hm_mcp_launcher::clear_hm_step_path {} {
    variable hm_step_path
    set hm_step_path ""
    refresh_hm_step_display
}

proc ::hm_mcp_launcher::hm_step_display_text {} {
    variable hm_step_path
    set p [string trim $hm_step_path]
    if {$p eq ""} {
        return "拖拽 HM STEP/HM 到这里 · 点击选择"
    }
    return "已选择 · [file tail $p]"
}

proc ::hm_mcp_launcher::refresh_hm_step_display {} {
    set w [panel_window]
    if {[winfo exists $w.root.main.left.hmstepbox.text]} {
        $w.root.main.left.hmstepbox.text configure -text [hm_step_display_text]
    }
    if {[winfo exists $w.root.main.left.hmstepbox.canvas]} {
        $w.root.main.left.hmstepbox.canvas itemconfigure hmsteptext -text [hm_step_display_text]
    }
}

proc ::hm_mcp_launcher::set_hm_step_from_drop {raw} {
    variable hm_step_path
    set data [string trim $raw]
    if {$data eq ""} {
        return
    }
    set open_brace [format %c 123]
    set close_brace [format %c 125]
    if {[string index $data 0] eq $open_brace} {
        set close_at [string first $close_brace $data]
        if {$close_at > 0} {
            set data [string range $data 1 [expr {$close_at - 1}]]
        }
    } else {
        set data [lindex $data 0]
    }
    set data [string trim $data "\""]
    if {$data ne ""} {
        set normalized [file normalize $data]
        if {![file exists $normalized]} {
            tk_messageBox -icon warning -title "HM 输入文件不存在" -message "拖入的 HM STEP/HM 文件不存在或无法访问：\n$normalized"
            return
        }
        set ext [string tolower [file extension $normalized]]
        if {[lsearch -exact {.stp .step .hm} $ext] < 0} {
            tk_messageBox -icon warning -title "HM 输入格式不支持" -message "请拖入 .stp / .step / .hm 文件：\n$normalized"
            return
        }
        set hm_step_path $normalized
        refresh_hm_step_display
    }
}

proc ::hm_mcp_launcher::find_ansa_base {} {
    variable project_dir
    set candidates {}
    set configured_file [file normalize [file join $project_dir ansa_auto_mesh_dir.txt]]
    if {[file exists $configured_file]} {
        if {![catch {
            set fh [open $configured_file r]
            fconfigure $fh -encoding utf-8
            set configured_path [string trim [read $fh]]
            close $fh
        }]} {
            if {$configured_path ne ""} {
                lappend candidates [file normalize $configured_path]
            }
        } else {
            catch {close $fh}
        }
    }
    if {[info exists ::env(ANSA_AUTO_MESH_DIR)] && [string trim $::env(ANSA_AUTO_MESH_DIR)] ne ""} {
        lappend candidates [file normalize $::env(ANSA_AUTO_MESH_DIR)]
    }
    lappend candidates \
        [file normalize [file join $project_dir ansa_mesh_tool]] \
        [file normalize [file join [file dirname $project_dir] ansa_auto ansa_mesh_tool]] \
        [file normalize [file join [file dirname [file dirname $project_dir]] ansa_auto ansa_mesh_tool]] \
        [file normalize "E:/ansa_auto/ansa_mesh_tool"]
    foreach candidate $candidates {
        if {[file exists [file join $candidate main.xaml]] && [file exists [file join $candidate runner.py]]} {
            return $candidate
        }
    }
    return ""
}

proc ::hm_mcp_launcher::enable_hm_step_drop {widget} {
    variable project_dir
    set ansa_base [find_ansa_base]
    set dnd_candidates {}
    if {$ansa_base ne ""} {
        lappend dnd_candidates \
            [file normalize [file join $ansa_base vendor tkinterdnd2 tkdnd win-x64]] \
            [file normalize [file join $ansa_base vendor tkinterdnd2 tkdnd win-x64-tcl9]]
    }
    lappend dnd_candidates \
        [file normalize [file join [file dirname $project_dir] ansa_auto ansa_mesh_tool vendor tkinterdnd2 tkdnd win-x64]] \
        [file normalize [file join [file dirname $project_dir] ansa_auto ansa_mesh_tool vendor tkinterdnd2 tkdnd win-x64-tcl9]] \
        [file normalize "E:/ansa_auto/ansa_mesh_tool/vendor/tkinterdnd2/tkdnd/win-x64"] \
        [file normalize "E:/ansa_auto/ansa_mesh_tool/vendor/tkinterdnd2/tkdnd/win-x64-tcl9"]
    foreach candidate $dnd_candidates {
        if {[file exists $candidate]} {
            lappend ::auto_path $candidate
        }
    }
    if {[catch {package require tkdnd}]} {
        return 0
    }
    if {[catch {
        tkdnd::drop_target register $widget DND_Files
        bind $widget <<Drop>> {::hm_mcp_launcher::set_hm_step_from_drop %D}
    }]} {
        return 0
    }
    return 1
}

proc ::hm_mcp_launcher::open_ansa_auto_mesh {} {
    variable project_dir
    set ansa_base [find_ansa_base]
    set candidates [list \
        [file normalize [file join $project_dir "启动_ANSA_桥接.vbs"]] \
    ]
    if {$ansa_base ne ""} {
        lappend candidates [file normalize [file join $ansa_base "启动 ANSA Auto Mesh.vbs"]]
    }
    lappend candidates \
        [file normalize [file join [file dirname $project_dir] ansa_auto ansa_mesh_tool "启动 ANSA Auto Mesh.vbs"]] \
        [file normalize [file join [file dirname [file dirname $project_dir]] ansa_auto ansa_mesh_tool "启动 ANSA Auto Mesh.vbs"]] \
        [file normalize "E:/ansa_auto/ansa_mesh_tool/启动 ANSA Auto Mesh.vbs"]
    set launcher ""
    foreach candidate $candidates {
        if {[file exists $candidate]} {
            set launcher $candidate
            break
        }
    }
    if {$launcher eq ""} {
        set message "没有找到 ANSA Auto Mesh 启动器。\n\n请确认实验入口或正式入口存在。"
        append_log "$message\n"
        tk_messageBox -icon warning -title "找不到 ANSA 工具" -message $message
        return
    }
    append_log "正在打开 ANSA Auto Mesh：$launcher\n"
    if {[catch {exec cmd /c start "" [file nativename $launcher] &} err]} {
        append_log "打开 ANSA Auto Mesh 失败：$err\n"
        tk_messageBox -icon warning -title "打开 ANSA 失败" -message $err
    }
}

proc ::hm_mcp_launcher::start_parallel_hm_ansa {} {
    variable current_pid
    variable ansa_bridge_state_path
    variable project_dir
    variable python_exe
    variable current_log
    variable current_stamp
    variable current_mode
    variable current_stop_file
    variable last_log_size
    variable last_pid_check_ms
    variable background_input_path

    if {$current_pid ne ""} {
        set_status "当前已有流程在运行"
        append_log "\n当前已有后台流程在运行，先停止或等待它结束。\n"
        return
    }

    ensure_directories
    set current_stamp [make_stamp]
    set current_mode "parallel"
    set current_log [file normalize [file join $project_dir runs "panel_parallel_hm_ansa_$current_stamp.log"]]
    set current_stop_file [file normalize [file join $project_dir runs "stop_parallel_$current_stamp.flag"]]
    if {[file exists $current_stop_file]} {
        catch {file delete $current_stop_file}
    }
    set last_log_size 0
    set last_pid_check_ms 0
    replace_log ""
    normalize_mesh_parameters

    if {[catch {set hm_input [normalized_hm_step_path]} err]} {
        set_status "HM STEP 输入无效"
        append_log "HM+ANSA 同时划分无法启动：$err\n"
        tk_messageBox -icon warning -title "HM STEP 输入无效" -message $err
        return
    }

    if {$hm_input eq ""} {
        set_status "正在保存当前 HM 模型快照"
        append_log "HM+ANSA 同时划分：HM STEP 为空，正在尝试保存当前 HyperMesh 模型快照。\n"
        if {[catch {set snapshot_path [save_background_snapshot]} err]} {
            set_status "HM 输入为空且当前模型不可用"
            append_log "HM+ANSA 同时划分无法启动：$err\n"
            tk_messageBox -icon warning -title "HM 输入缺失" -message "同时划分需要 HM 有输入。\n\n你可以：\n1. 在左侧 HM STEP/HM 输入框选择或拖入 HM 用的 STEP/HM；或\n2. 先在当前 HyperMesh 界面导入模型。\n\n当前尝试保存 HM 快照失败：\n$err"
            return
        }
        set background_input_path $snapshot_path
        append_log "HM+ANSA 同时划分：HM 将使用当前模型快照：$snapshot_path\n"
    } else {
        set background_input_path $hm_input
        append_log "HM+ANSA 同时划分：HM 将使用 $hm_input\n"
    }

    if {![::hm_mcp_launcher::wait_for_file $ansa_bridge_state_path 3000]} {
        set message "ANSA 侧还没有可读取的 STEP 选择状态。\n\n请先点击“打开ANSA划分”，在 ANSA 界面拖入/选择 ANSA STEP。\n\n状态文件应写入：\n$ansa_bridge_state_path"
        set_status "等待 ANSA STEP"
        append_log "$message\n"
        tk_messageBox -icon info -title "请先选择 ANSA STEP" -message $message
        return
    }
    set ansa_step ""
    if {[catch {
        set fh [open $ansa_bridge_state_path r]
        fconfigure $fh -encoding utf-8
        set bridge_text [read $fh]
        close $fh
        if {[regexp {"step_path"[ \t\r\n]*:[ \t\r\n]*"([^"]+)"} $bridge_text -> parsed_step]} {
            set ansa_step [string map {\\\\ \\} $parsed_step]
        }
    } err]} {
        catch {close $fh}
        set message "读取 ANSA STEP 状态失败：$err\n\n状态文件：$ansa_bridge_state_path"
        set_status "ANSA STEP 状态读取失败"
        append_log "$message\n"
        tk_messageBox -icon warning -title "ANSA STEP 状态读取失败" -message $message
        return
    }
    if {$ansa_step eq "" || ![file exists $ansa_step]} {
        set message "ANSA STEP 状态文件存在，但里面的 STEP 路径无效。\n\n请重新点击“打开ANSA划分”，在 ANSA 界面重新拖入/选择 ANSA STEP。\n\n状态文件：$ansa_bridge_state_path\n读取到：$ansa_step"
        set_status "ANSA STEP 无效"
        append_log "$message\n"
        tk_messageBox -icon warning -title "ANSA STEP 无效" -message $message
        return
    }

    append_log "检测到 ANSA STEP：$ansa_step\n"

    set hm_cmd [build_command background]
    set hm_argv_file [file normalize [file join $project_dir runs "parallel_hm_args_$current_stamp.txt"]]
    if {[catch {write_argv_file $hm_argv_file $hm_cmd} err]} {
        set_status "写入 HM 参数失败"
        append_log "HM+ANSA 同时划分无法启动：写入 HM 参数失败：$err\n"
        tk_messageBox -icon warning -title "写入 HM 参数失败" -message $err
        return
    }
    if {![::hm_mcp_launcher::wait_for_file $hm_argv_file 2000]} {
        set message "HM 参数临时文件尚未写入完成：$hm_argv_file"
        set_status "HM 参数文件缺失"
        append_log "$message\n"
        tk_messageBox -icon warning -title "HM 参数文件缺失" -message $message
        return
    }

    set coordinator [file normalize [file join $project_dir parallel_hm_ansa.py]]
    if {![file exists $coordinator]} {
        set message "未找到并行协调器：$coordinator"
        set_status "并行协调器缺失"
        append_log "$message\n"
        tk_messageBox -icon warning -title "并行协调器缺失" -message $message
        return
    }
    set ansa_base [find_ansa_base]
    if {$ansa_base eq ""} {
        set message "没有找到 ANSA Auto Mesh 工具目录。\n\n请确认 ansa_mesh_tool 存在，或设置环境变量 ANSA_AUTO_MESH_DIR 指向 ansa_mesh_tool。"
        set_status "ANSA 工具目录缺失"
        append_log "$message\n"
        tk_messageBox -icon warning -title "ANSA 工具目录缺失" -message $message
        return
    }
    set cmd [list $python_exe $coordinator \
        --hm-argv-file $hm_argv_file \
        --ansa-state $ansa_bridge_state_path \
        --ansa-base $ansa_base \
        --project-dir $project_dir \
        --stamp $current_stamp \
        --stop-file $current_stop_file]

    set old_pwd [pwd]
    set_status "HM+ANSA 同时划分运行中"
    append_log "正在启动 HM+ANSA 同时划分协调器...\n日志文件：$current_log\n\n"
    if {[catch {
        cd $project_dir
        set pids [start_hidden_logged_process $cmd $current_log]
    } err]} {
        catch {cd $old_pwd}
        set_status "并行启动失败"
        append_log "无法启动 HM+ANSA 同时划分：$err\n"
        tk_messageBox -icon warning -title "并行启动失败" -message $err
        return
    }
    catch {cd $old_pwd}

    set current_pid [lindex $pids 0]
    set_status "HM+ANSA 同时划分运行中，PID=$current_pid"
    append_log "已启动协调器，PID=$current_pid。\n\n"
    keep_panel_visible
    after 1000 ::hm_mcp_launcher::poll_log
}

proc ::hm_mcp_launcher::add_row {parent row label variable hint} {
    ttk::label $parent.l$row -text $label -anchor w -style HMLabel.TLabel
    ttk::entry $parent.e$row -textvariable $variable -width 16 -style HM.TEntry
    grid $parent.l$row -row $row -column 0 -sticky ew -padx {0 10} -pady 4
    grid $parent.e$row -row $row -column 1 -sticky w -pady 4
    if {$hint ne ""} {
        ttk::label $parent.h$row -text $hint -anchor w -style HMHunt.TLabel -wraplength 260 -justify left
        grid $parent.h$row -row $row -column 2 -columnspan 2 -sticky ew -padx {8 0} -pady 4
    }
}

proc ::hm_mcp_launcher::build_ui {} {
    if {[catch {package require Tk} err]} {
        puts "无法加载 Tk，不能显示弹窗：$err"
        return
    }

    catch {package require Ttk}
    catch {
        set current_theme [ttk::style theme use]
        if {![regexp {^hw} $current_theme]} {
            foreach candidate [ttk::style theme names] {
                if {[regexp {^hw} $candidate]} {
                    ttk::style theme use $candidate
                    break
                }
            }
        }
    }
    set w .hm_mcp_meshing_launcher
    if {[winfo exists $w]} {
        destroy $w
    }

    toplevel $w
    wm title $w "HyperMesh 自动网格划分"
    wm minsize $w 1220 720
    wm geometry $w 1320x1260+30+40
    catch {wm attributes $w -topmost 1}

    catch {
        ttk::style configure HMRoot.TFrame -background "#edf1f7"
        ttk::style configure HMCard.TFrame -background "#ffffff" -relief flat
        ttk::style configure HMTitle.TLabel -background "#edf1f7" -foreground "#172033" -font {"Microsoft YaHei UI" 16 bold}
        ttk::style configure HMSub.TLabel -background "#edf1f7" -foreground "#5c6675" -font {"Microsoft YaHei UI" 10}
        ttk::style configure HMSection.TLabelframe -background "#ffffff" -foreground "#172033" -font {"Microsoft YaHei UI" 13 bold}
        ttk::style configure HMSection.TLabelframe.Label -background "#ffffff" -foreground "#172033" -font {"Microsoft YaHei UI" 13 bold}
        ttk::style configure HMLabel.TLabel -background "#ffffff" -foreground "#1e293b" -font {"Microsoft YaHei UI" 12}
        ttk::style configure HMHunt.TLabel -background "#ffffff" -foreground "#697386" -font {"Microsoft YaHei UI" 9}
        ttk::style configure HMStatus.TLabel -background "#dbeafe" -foreground "#17324d" -font {"Microsoft YaHei UI" 12 bold} -padding {10 6}
        ttk::style configure HM.TEntry -font {"Microsoft YaHei UI" 12} -padding 5
        ttk::style configure HM.TButton -font {"Microsoft YaHei UI" 12 bold} -padding {14 7}
        ttk::style configure HMStop.TButton -font {"Microsoft YaHei UI" 12 bold} -padding {14 7}
        ttk::style configure HMCheck.TCheckbutton -background "#ffffff" -foreground "#1e293b" -font {"Microsoft YaHei UI" 11}
    }

    ttk::frame $w.root -padding 16 -style HMRoot.TFrame
    grid $w.root -row 0 -column 0 -sticky nsew
    grid rowconfigure $w 0 -weight 1
    grid columnconfigure $w 0 -weight 1
    grid columnconfigure $w.root 0 -weight 1
    grid rowconfigure $w.root 5 -weight 1

    ttk::label $w.root.title -text "HyperMesh 自动网格划分面板" -style HMTitle.TLabel
    ttk::label $w.root.sub -text "导入模型后，点击开始划分即可执行完整流程；运行日志会实时显示在下方。" -style HMSub.TLabel
    grid $w.root.title -row 0 -column 0 -sticky ew
    grid $w.root.sub -row 1 -column 0 -sticky ew -pady {2 8}

    ttk::label $w.root.status -textvariable ::hm_mcp_launcher::status_text -style HMStatus.TLabel -anchor w
    grid $w.root.status -row 2 -column 0 -sticky ew -pady {0 10}

    ttk::frame $w.root.main -style HMRoot.TFrame
    grid $w.root.main -row 3 -column 0 -sticky ew -pady {0 10}
    grid columnconfigure $w.root.main 0 -weight 56
    grid columnconfigure $w.root.main 1 -weight 44
    grid rowconfigure $w.root.main 0 -weight 1

    ttk::labelframe $w.root.main.left -text "项目和尺寸限制" -padding 12 -style HMSection.TLabelframe
    grid $w.root.main.left -row 0 -column 0 -sticky nsew -padx {0 16}
    grid columnconfigure $w.root.main.left 0 -weight 0 -minsize 145
    grid columnconfigure $w.root.main.left 1 -weight 0 -minsize 100
    grid columnconfigure $w.root.main.left 2 -weight 1 -minsize 220
    grid columnconfigure $w.root.main.left 3 -weight 0 -minsize 76
    grid rowconfigure $w.root.main.left 14 -weight 1
    ttk::frame $w.root.main.left.hmstepbox -style HMRoot.TFrame -padding 0
    canvas $w.root.main.left.hmstepbox.canvas -width 1 -height 92 -background "#eaf4ff" -highlightthickness 1 -highlightbackground "#75b7ff" -borderwidth 0
    $w.root.main.left.hmstepbox.canvas create text 1 1 -text [::hm_mcp_launcher::hm_step_display_text] -tags hmsteptext -fill "#0b559f" -font {"Microsoft YaHei UI" 12 bold} -anchor center -justify center -width 420
    button $w.root.main.left.hmstepbox.clear -text "×" -font {"Microsoft YaHei UI" 10 bold} -command ::hm_mcp_launcher::clear_hm_step_path -relief flat -background "#f8fbff" -foreground "#667085" -width 2
    grid $w.root.main.left.hmstepbox -row 0 -column 0 -columnspan 4 -sticky ew -pady {0 16}
    grid $w.root.main.left.hmstepbox.canvas -row 0 -column 0 -sticky ew
    grid $w.root.main.left.hmstepbox.clear -row 0 -column 0 -sticky ne -padx {0 6} -pady {6 0}
    grid columnconfigure $w.root.main.left.hmstepbox 0 -weight 1
    bind $w.root.main.left.hmstepbox.canvas <Configure> {%W coords hmsteptext [expr {%w / 2}] [expr {%h / 2}]; %W itemconfigure hmsteptext -width [expr {%w - 44}]}
    bind $w.root.main.left.hmstepbox <Button-1> ::hm_mcp_launcher::browse_hm_step_path
    bind $w.root.main.left.hmstepbox.canvas <Button-1> ::hm_mcp_launcher::browse_hm_step_path
    if {[::hm_mcp_launcher::enable_hm_step_drop $w.root.main.left.hmstepbox.canvas]} {
        append_log "HM STEP 投放框已启用拖拽导入。\n"
    }
    if {[::hm_mcp_launcher::enable_hm_step_drop $w.root.main.left.hmstepbox]} {
        append_log "HM STEP 输入框已启用拖拽导入。\n"
    }
    ttk::label $w.root.main.left.outl -text "输出 HM 文件" -anchor w -style HMLabel.TLabel
    ttk::frame $w.root.main.left.outrow -style HMCard.TFrame
    ttk::entry $w.root.main.left.outrow.oute -textvariable ::hm_mcp_launcher::output_path -style HM.TEntry
    ttk::button $w.root.main.left.outrow.outb -text "浏览" -style HM.TButton -command ::hm_mcp_launcher::browse_output_path
    grid $w.root.main.left.outl -row 1 -column 0 -sticky ew -padx {0 12} -pady {3 7}
    grid $w.root.main.left.outrow -row 1 -column 1 -columnspan 3 -sticky ew -pady {3 7}
    pack $w.root.main.left.outrow.outb -side right -padx {8 0}
    pack $w.root.main.left.outrow.oute -side left -fill x -expand 1
    ttk::separator $w.root.main.left.sep1 -orient horizontal
    grid $w.root.main.left.sep1 -row 2 -column 0 -columnspan 4 -sticky ew -pady {9 10}
    add_row $w.root.main.left 3 "drag 尺寸下限" ::hm_mcp_launcher::drag_element_size_min "自动尺寸下限"
    add_row $w.root.main.left 4 "drag 尺寸上限" ::hm_mcp_launcher::drag_element_size_max "自动尺寸上限"
    add_row $w.root.main.left 5 "tetra目标下限" ::hm_mcp_launcher::tetra_element_size_min "目标尺寸下限"
    add_row $w.root.main.left 6 "tetra目标上限" ::hm_mcp_launcher::tetra_element_size_max "目标尺寸上限"
    add_row $w.root.main.left 7 "tetra最小下限" ::hm_mcp_launcher::tetra_min_element_size_min "最小尺寸下限"
    add_row $w.root.main.left 8 "tetra最小上限" ::hm_mcp_launcher::tetra_min_element_size_max "最小尺寸上限"
    add_row $w.root.main.left 9 "spin份数下限" ::hm_mcp_launcher::spin_density_min "半径计算下限"
    add_row $w.root.main.left 10 "spin份数上限" ::hm_mcp_launcher::spin_density_max "半径计算上限"
    ttk::checkbutton $w.root.main.left.auto -text "开始前自动建立/刷新 HyperMesh 连接" -variable ::hm_mcp_launcher::auto_listener -style HMCheck.TCheckbutton
    add_row $w.root.main.left 11 "spin section size min" ::hm_mcp_launcher::spin_section_element_size_min "2D size min"
    add_row $w.root.main.left 12 "spin section size max" ::hm_mcp_launcher::spin_section_element_size_max "2D size max"
    grid $w.root.main.left.auto -row 13 -column 0 -columnspan 4 -sticky w -pady {9 0}
    ttk::frame $w.root.main.left.fill -style HMCard.TFrame
    grid $w.root.main.left.fill -row 14 -column 0 -columnspan 4 -sticky nsew

    ttk::labelframe $w.root.main.right -text "质量和修复参数" -padding 12 -style HMSection.TLabelframe
    grid $w.root.main.right -row 0 -column 1 -sticky nsew -padx {0 0}
    grid columnconfigure $w.root.main.right 1 -weight 0 -minsize 92
    grid columnconfigure $w.root.main.right 2 -weight 0 -minsize 220
    ttk::checkbutton $w.root.main.right.dragaspect -text "drag三层" -variable ::hm_mcp_launcher::drag_aspect_guard -style HMCheck.TCheckbutton
    grid $w.root.main.right.dragaspect -row 9 -column 0 -columnspan 3 -sticky w -pady {7 0}
    add_row $w.root.main.right 0 "drag 贴合比例" ::hm_mcp_launcher::drag_fit_tolerance_ratio "越小越严格"
    add_row $w.root.main.right 1 "drag 重试次数" ::hm_mcp_launcher::drag_retry_count ""
    add_row $w.root.main.right 2 "tetra 最大偏差" ::hm_mcp_launcher::tetra_max_deviation "2D max_dev"
    add_row $w.root.main.right 3 "tetra 特征角" ::hm_mcp_launcher::tetra_feature_angle ""
    add_row $w.root.main.right 4 "tetra 增长率" ::hm_mcp_launcher::tetra_growth_rate ""
    add_row $w.root.main.right 5 "tetra 贴合比例" ::hm_mcp_launcher::tetra_fit_tolerance_ratio ""
    add_row $w.root.main.right 6 "最大 chord dev 下降值" ::hm_mcp_launcher::tetra_chord_dev_degrade_delta "超过则退回"
    add_row $w.root.main.right 7 "目标 vol skew" ::hm_mcp_launcher::tetra_target_vol_skew ""
    add_row $w.root.main.right 8 "修复 vol skew" ::hm_mcp_launcher::tetra_repair_vol_skew ""
    ttk::checkbutton $w.root.main.right.gearrefine -text "启用齿面加厚/加密模型" -variable ::hm_mcp_launcher::use_gear_tooth_refinement -style HMCheck.TCheckbutton
    grid $w.root.main.right.gearrefine -row 10 -column 0 -columnspan 3 -sticky w -pady {7 0}
    add_row $w.root.main.right 11 "齿面tetra下限" ::hm_mcp_launcher::gear_tooth_element_size_min "固定尺寸"
    add_row $w.root.main.right 12 "齿面tetra上限" ::hm_mcp_launcher::gear_tooth_element_size_max "固定尺寸"
    add_row $w.root.main.right 13 "齿面最小下限" ::hm_mcp_launcher::gear_tooth_min_element_size_min "固定最小"
    add_row $w.root.main.right 14 "齿面最小上限" ::hm_mcp_launcher::gear_tooth_min_element_size_max "固定最小"
    add_row $w.root.main.right 15 "齿面特征角" ::hm_mcp_launcher::gear_tooth_feature_angle "小30%"

    ttk::labelframe $w.root.logbox -text "运行日志" -padding 12 -style HMSection.TLabelframe
    grid $w.root.logbox -row 5 -column 0 -sticky nsew -pady {0 10}
    grid rowconfigure $w.root.logbox 0 -weight 1
    grid columnconfigure $w.root.logbox 0 -weight 1
    text $w.root.logbox.text -height 11 -wrap none -state disabled -font {"Consolas" 11} -background "#101828" -foreground "#e5e7eb" -insertbackground "#e5e7eb" -relief flat -borderwidth 0
    ttk::scrollbar $w.root.logbox.ys -orient vertical -command "$w.root.logbox.text yview"
    ttk::scrollbar $w.root.logbox.xs -orient horizontal -command "$w.root.logbox.text xview"
    $w.root.logbox.text configure -yscrollcommand "$w.root.logbox.ys set" -xscrollcommand "$w.root.logbox.xs set"
    grid $w.root.logbox.text -row 0 -column 0 -sticky nsew
    grid $w.root.logbox.ys -row 0 -column 1 -sticky ns
    grid $w.root.logbox.xs -row 1 -column 0 -sticky ew

    ttk::frame $w.root.actions -style HMRoot.TFrame
    grid $w.root.actions -row 6 -column 0 -sticky ew
    ttk::label $w.root.actions.hmgroup -text "HM 相关" -style HMSub.TLabel
    ttk::label $w.root.actions.extgroup -text "扩展/联合" -style HMSub.TLabel
    ttk::button $w.root.actions.connect -text "仅建立连接" -style HM.TButton -command {
        ::hm_mcp_launcher::set_status "正在建立 HyperMesh 连接"
        ::hm_mcp_launcher::append_log "正在建立 HyperMesh 连接...\n"
        if {[catch {set p [::hm_mcp_launcher::ensure_listener]} e]} {
            ::hm_mcp_launcher::set_status "连接失败"
            ::hm_mcp_launcher::append_log "连接失败：$e\n"
            ::hm_mcp_launcher::append_log [::hm_mcp_launcher::manual_connection_help_text]
        } else {
            ::hm_mcp_launcher::set_status "连接成功"
            ::hm_mcp_launcher::append_log "连接成功：$p\n当前端口：$::hm_mcp_launcher::port\n"
        }
    }
    ttk::button $w.root.actions.run -text "HM划分" -style HM.TButton -command ::hm_mcp_launcher::start_workflow
    ttk::button $w.root.actions.background -text "HM后台划分" -style HM.TButton -command {::hm_mcp_launcher::start_workflow background}
    ttk::button $w.root.actions.ansa -text "打开ANSA划分" -style HM.TButton -command ::hm_mcp_launcher::open_ansa_auto_mesh
    ttk::button $w.root.actions.parallel -text "HM+ANSA同时划分" -style HM.TButton -command ::hm_mcp_launcher::start_parallel_hm_ansa
    ttk::button $w.root.actions.gearpreview -text "只划分齿面网格" -style HM.TButton -command {::hm_mcp_launcher::start_workflow gear_preview}
    ttk::button $w.root.actions.deletegearpreview -text "删除齿面网格" -style HM.TButton -command {::hm_mcp_launcher::start_workflow delete_gear_preview}
    ttk::button $w.root.actions.stop -text "停止" -style HMStop.TButton -command ::hm_mcp_launcher::stop_workflow
    grid $w.root.actions.hmgroup -row 0 -column 0 -sticky w -padx {0 10} -pady {0 4}
    grid $w.root.actions.connect -row 0 -column 1 -padx {0 12} -pady {0 4}
    grid $w.root.actions.run -row 0 -column 2 -padx 12 -pady {0 4}
    grid $w.root.actions.background -row 0 -column 3 -padx 12 -pady {0 4}
    grid $w.root.actions.stop -row 0 -column 4 -padx 12 -pady {0 4}
    grid $w.root.actions.extgroup -row 1 -column 0 -sticky w -padx {0 10} -pady {6 0}
    grid $w.root.actions.ansa -row 1 -column 1 -padx {0 12} -pady {6 0}
    grid $w.root.actions.parallel -row 1 -column 2 -padx 12 -pady {6 0}
    grid $w.root.actions.gearpreview -row 1 -column 3 -padx 12 -pady {6 0}
    grid $w.root.actions.deletegearpreview -row 1 -column 4 -padx 12 -pady {6 0}
}

::hm_mcp_launcher::build_ui

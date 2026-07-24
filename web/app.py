#!/usr/bin/env python3
"""
A股智能选股 · Trade-AI — Streamlit 网页界面

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import sys
import os
import threading
import time
import queue
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st
import pandas as pd

# 把仓库根目录加入 Python 路径（无论从哪里启动）
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ============ 页面配置（必须第一行调用） ============
st.set_page_config(
    page_title="A股智能选股 · Trade-AI",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============ 常量 ============

POOL_OPTIONS = {
    "沪深300（大盘蓝筹，约300只）": "hs300",
    "中证500（中盘成长，约500只）": "zz500",
    "中证1000（小盘潜力，约1000只）": "zz1000",
    "全A股（全市场扫描，约8000+只）": "all",
}

STRATEGY_OPTIONS = {
    "多因子策略（估值+盈利+规模，综合评分）": "multi_factor",
    "低PE价值策略（低估值高盈利）": "pe_value",
    "三维评分策略（基本面+技术面+情绪面）": "three_dimensional",
}

MODE_OPTIONS = {
    "快速采样（约 20-60 秒，采样随机股票）": "fast",
    "全市场扫描（约 15-20 分钟，覆盖全部股票）": "full",
}

DISCLAIMER = (
    "⚠️ **免责声明**：本工具仅供学习研究，**不构成任何投资建议**。"
    "数据来自 Baostock，存在延迟；策略未经充分回测；"
    "投资决策请自行判断、**风险自负**。"
)

NETWORK_TIPS = (
    "排查建议：① 关闭 VPN 走国内直连  "
    "② 降低采样量后重试  "
    "③ 稍等片刻后再试（Baostock 在并发高峰时可能返回错误）"
)

# ============ 日志设置 ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("trade-ai.web")

# ============ Session State 初始化 ============

def _init_state():
    defaults = {
        "running": False,
        "result": None,
        "error": None,
        "progress_messages": [],
        "thread": None,
        "run_id": 0,
        "msg_queue": None,        # thread-safe queue for progress messages
        "result_container": {},   # shared dict for engine result/error
        "stop_event": None,       # threading.Event to signal the engine to stop
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()

# ============ 后台运行函数 ============

def _run_engine_in_background(
    pool: str,
    strategy_name: str,
    sample_size: Optional[int],
    use_cache: bool,
    run_id: int,
    msg_queue: "queue.Queue[tuple]",
    result_container: dict,
    stop_event: threading.Event,
):
    """在后台线程中运行选股引擎，通过线程安全队列传递进度消息
    
    队列消息格式为 (tag, payload)：
      ("progress", message_str) — 进度文字
      ("done", None)            — 完成
      ("error", error_str)      — 错误
    """
    try:
        from core.engine import StockPickerEngine

        def _progress(msg: str):
            msg_queue.put(("progress", msg))

        engine = StockPickerEngine(
            config_path=str(_ROOT / "config"),
            cache_dir=str(_ROOT / "data" / "cache"),
            reports_dir=str(_ROOT / "reports" / "daily"),
        )
        result = engine.run(
            pool=pool,
            strategy_name=strategy_name,
            sample_size=sample_size,
            use_cache=use_cache,
            send_qq=False,
            top_n=50,
            progress_callback=_progress,
            stop_event=stop_event,
        )
        result_container["result"] = result
        msg_queue.put(("done", None))

    except Exception as exc:
        logger.exception("引擎运行异常")
        result_container["error"] = str(exc)
        msg_queue.put(("error", str(exc)))


# ============ 主页面 ============

def main():
    # 标题
    st.title("📈 A股智能选股 · Trade-AI")
    st.caption("基于 Baostock 免费数据源，Docker 一键部署，网页直接使用")

    # 免责声明（固定展示）
    st.info(DISCLAIMER)

    # -------- 侧边栏 --------
    with st.sidebar:
        st.header("⚙️ 选股参数")

        pool_label = st.selectbox("📦 股票池", list(POOL_OPTIONS.keys()), index=0)
        pool = POOL_OPTIONS[pool_label]

        strategy_label = st.selectbox("🎯 选股策略", list(STRATEGY_OPTIONS.keys()), index=0)
        strategy_name = STRATEGY_OPTIONS[strategy_label]

        mode_label = st.selectbox("🚀 运行模式", list(MODE_OPTIONS.keys()), index=0)
        is_fast = MODE_OPTIONS[mode_label] == "fast"

        if is_fast:
            sample_size = st.slider("采样数量", min_value=50, max_value=500, value=200, step=50)
        else:
            sample_size = None
            st.caption("⚠️ 全市场扫描约需 15-20 分钟，请耐心等待。")

        use_cache = st.checkbox("💾 使用缓存加速（当日内避免重复请求）", value=True)

        st.divider()
        st.caption("数据来源：[Baostock](https://baostock.com)（免费，无需 API Key）")
        st.caption("开源致谢：[striferxu/stock-picker-plus](https://github.com/striferxu/stock-picker-plus)（GPLv3）")

    # -------- 操作按钮 --------
    col_btn, col_status = st.columns([2, 5])

    with col_btn:
        start_clicked = st.button(
            "🔍 开始选股",
            type="primary",
            disabled=st.session_state.running,
            use_container_width=True,
        )
        if st.session_state.running:
            stop_clicked = st.button("⏹ 停止", use_container_width=True)
            if stop_clicked:
                # 先通知引擎停止（通过 Event），再清除状态
                stop_ev: Optional[threading.Event] = st.session_state.get("stop_event")
                if stop_ev is not None:
                    stop_ev.set()
                st.session_state.running = False
                st.session_state.run_id += 1  # 使后台线程结果失效
                st.session_state.progress_messages = []
                st.session_state.msg_queue = None
                st.session_state.stop_event = None
                st.rerun()

    # -------- 启动后台任务 --------
    if start_clicked and not st.session_state.running:
        st.session_state.running = True
        st.session_state.result = None
        st.session_state.error = None
        st.session_state.progress_messages = []
        st.session_state.run_id += 1
        run_id = st.session_state.run_id

        # 创建停止信号 Event（供用户点击「停止」时触发）
        stop_ev = threading.Event()
        st.session_state.stop_event = stop_ev

        # 使用线程安全队列传递消息，result_container 存入 session_state 避免修改 Thread 对象
        msg_q: queue.Queue = queue.Queue()
        result_container: dict = {}
        st.session_state.msg_queue = msg_q
        st.session_state.result_container = result_container

        t = threading.Thread(
            target=_run_engine_in_background,
            args=(pool, strategy_name, sample_size, use_cache, run_id,
                  msg_q, result_container, stop_ev),
            daemon=True,
        )
        t.start()
        st.session_state.thread = t
        st.rerun()

    # -------- 运行中：进度展示 --------
    if st.session_state.running:
        with col_status:
            st.write("")
        progress_placeholder = st.empty()

        with st.spinner("正在运行选股引擎，请稍候..."):
            # 轮询后台线程状态，从线程安全队列读取消息
            msg_q = st.session_state.get("msg_queue")
            thread = st.session_state.get("thread")
            container = st.session_state.get("result_container", {})

            while st.session_state.running:
                # 排空队列中的消息
                if msg_q is not None:
                    while True:
                        try:
                            tag, payload = msg_q.get_nowait()
                            if tag == "progress":
                                st.session_state.progress_messages.append(payload)
                            elif tag in ("done", "error"):
                                # 线程完成，从 session_state 中的 container 读取结果
                                if tag == "done":
                                    st.session_state.result = container.get("result")
                                else:
                                    st.session_state.error = container.get("error", payload)
                                st.session_state.running = False
                                break
                        except queue.Empty:
                            break

                # 刷新进度显示
                msgs = st.session_state.progress_messages
                if msgs:
                    with progress_placeholder.container():
                        st.caption("**运行日志：**")
                        for m in msgs[-10:]:
                            st.caption(f"  › {m}")

                if not st.session_state.running:
                    break

                time.sleep(1)

                # 兜底检查：线程已结束但未收到完成消息
                if thread is not None and not thread.is_alive():
                    if "result" in container:
                        st.session_state.result = container["result"]
                    elif "error" in container:
                        st.session_state.error = container["error"]
                    st.session_state.running = False
                    break

        st.rerun()

    # -------- 错误展示 --------
    if st.session_state.error:
        err_msg = st.session_state.error
        st.error(f"❌ 运行失败：{err_msg}")
        if "停止" in err_msg:
            st.caption("运行已被手动停止。")
        else:
            st.caption(NETWORK_TIPS)

    # -------- 结果展示 --------
    if st.session_state.result and not st.session_state.running:
        result = st.session_state.result

        if "error" in result and result["error"]:
            err_text: str = result["error"]
            if "停止" in err_text:
                st.warning(f"⏹ {err_text}")
            else:
                st.warning(f"⚠️ {err_text}")
                st.caption(NETWORK_TIPS)
            return

        selected: pd.DataFrame = result.get("selected", pd.DataFrame())
        stats: dict = result.get("stats", {})
        elapsed: float = result.get("elapsed_seconds", 0)
        excel_path: Optional[str] = result.get("excel_path")
        report_md: str = result.get("report_md", "")

        # 统计信息
        st.success(
            f"✅ 选股完成！耗时 **{elapsed:.1f}** 秒 | "
            f"扫描 **{stats.get('data_fetched', 0)}** 只 | "
            f"推荐 **{stats.get('selected', 0)}** 只"
        )

        if selected.empty:
            st.warning("未筛选出符合条件的股票，请尝试调整策略参数或切换股票池。")
            return

        # ---- 推荐股票表格 ----
        st.subheader(f"🏆 推荐股票榜（共 {len(selected)} 只）")

        # 选择展示列
        display_cols = []
        for c in ['代码', '名称', 'PE', 'PB', '收盘价', 'ROE', '营收增长率', '总分', '评级']:
            if c in selected.columns:
                display_cols.append(c)
        # 补充 total_score
        if '总分' not in display_cols and 'total_score' in selected.columns:
            display_cols.append('total_score')

        display_df = selected[display_cols].copy() if display_cols else selected.copy()

        # 格式化数值列
        for col in ['PE', 'PB']:
            if col in display_df.columns:
                display_df[col] = display_df[col].apply(
                    lambda x: f"{x:.1f}" if pd.notna(x) else '-')
        for col in ['收盘价']:
            if col in display_df.columns:
                display_df[col] = display_df[col].apply(
                    lambda x: f"{x:.2f}" if pd.notna(x) else '-')
        for col in ['ROE', '营收增长率']:
            if col in display_df.columns:
                display_df[col] = display_df[col].apply(
                    lambda x: f"{x:.1f}%" if pd.notna(x) else '-')
        for col in ['总分', 'total_score']:
            if col in display_df.columns:
                display_df[col] = display_df[col].apply(
                    lambda x: f"{x:.1f}" if pd.notna(x) else '-')

        st.dataframe(
            display_df.reset_index(drop=True),
            use_container_width=True,
            height=min(600, 40 + len(display_df) * 35),
        )

        # ---- 下载按钮 ----
        st.subheader("📥 下载报告")
        dl_col1, dl_col2 = st.columns(2)

        with dl_col1:
            if excel_path and Path(excel_path).exists():
                with open(excel_path, "rb") as f:
                    excel_bytes = f.read()
                fname = Path(excel_path).name
                st.download_button(
                    label="📊 下载 Excel 报告",
                    data=excel_bytes,
                    file_name=fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            else:
                st.button("📊 Excel 报告（生成中...）", disabled=True, use_container_width=True)

        with dl_col2:
            if report_md:
                ts = result.get("timestamp", datetime.now())
                md_filename = f"report_{ts.strftime('%Y%m%d_%H%M')}.md"
                st.download_button(
                    label="📝 下载 Markdown 报告",
                    data=report_md.encode("utf-8"),
                    file_name=md_filename,
                    mime="text/markdown",
                    use_container_width=True,
                )

        # ---- Markdown 预览 ----
        with st.expander("📋 查看 Markdown 报告全文"):
            st.markdown(report_md)


if __name__ == "__main__":
    main()

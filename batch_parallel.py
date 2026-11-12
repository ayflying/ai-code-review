"""仅并发模型请求：文档已准备，工作线程不读取Git或修改共享汇总。"""

from concurrent.futures import ThreadPoolExecutor
import subprocess
import time


def review_prepared(items, workers, deadline, request):
    """有界分波启动；不预提交全部批次，超预算不再发新请求。"""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(items), workers):
            wave = items[start:start + workers]
            pending = []
            for item in wave:
                index, diff, context, loaded, paths = item
                if time.monotonic() >= deadline:
                    yield item, None, [f"覆盖不完整：第 {index} 批达到启动时间预算，未调用模型。"], ""
                    continue
                print(f"AI审核：第 {index} 批开始（最多 {workers} 并发）。", flush=True)
                pending.append((item, pool.submit(request, diff, context, loaded)))
            # 固定汇总顺序，不让请求完成先后改变同分问题排序。
            for item, future in pending:
                try:
                    data, notes, provider = future.result()
                except (ValueError, OSError, subprocess.SubprocessError):
                    data, notes, provider = None, ["运行环境异常；保留其他批次结论。"], ""
                print(f"AI审核：第 {item[0]} 批{'已完成' if data is not None else '未取得有效结论'}。", flush=True)
                yield item, data, notes, provider

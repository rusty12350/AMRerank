
import asyncio
import sys
import os

import pandas as pd
from loguru import logger

# 重要：请确保您的项目结构中存在 src/workflow.py 文件，以便下面的导入能够成功。
from src.workflow import run_agent_workflow_async


def ask(
        question,
        debug=False,
        max_plan_iterations=1,
        max_step_num=3,
        enable_background_investigation=True,
):
    try:
        asyncio.run(
            run_agent_workflow_async(
                user_input=question,
                debug=debug,
                max_plan_iterations=max_plan_iterations,
                max_step_num=max_step_num,
                enable_background_investigation=enable_background_investigation,
            )
        )
    except Exception as e:
        logger.error(f"处理 '{question}' 时发生了一个错误: {e}")
        logger.error("将继续处理下一个任务...")


if __name__ == "__main__":
    file_to_process = "sample_date.xlsx"
    column_to_process = "fromLib"
    debug_mode = False
    plan_iterations = 1
    step_num = 3
    background_investigation = True
    logger.info("--- 启动默认批量处理模式 ---")
    logger.info(f"将要处理文件: '{file_to_process}'，目标列: '{column_to_process}'")

    try:
        # 步骤 1: 检查文件是否存在
        if not os.path.exists(file_to_process):
            logger.error(f"错误: 默认文件 '{file_to_process}' 未在当前目录找到。")
            logger.error("请确保 'ground_truth.xlsx' 文件与此脚本在同一目录下。")
            sys.exit(1)

        # 步骤 2: 根据文件扩展名读取文件
        # 这需要安装 'openpyxl' 库 (pip install openpyxl)
        if file_to_process.endswith('.xlsx'):
            logger.info("检测到 XLSX 文件，使用 read_excel 读取。")
            df = pd.read_excel(file_to_process)
        elif file_to_process.endswith('.csv'):
            logger.info("检测到 CSV 文件，使用 read_csv 读取。")
            df = pd.read_csv(file_to_process)
        else:
            logger.error(f"错误: 不支持的文件类型 '{os.path.splitext(file_to_process)[1]}'.")
            sys.exit(1)

        # 步骤 3: 检查目标列是否存在
        if column_to_process not in df.columns:
            logger.error(f"错误: 在文件 '{file_to_process}' 中找不到名为 '{column_to_process}' 的列。")
            sys.exit(1)

        # 步骤 4: 获取不重复的库列表（核心去重要求）
        source_libraries = df[column_to_process].dropna().unique()
        total_libs = len(source_libraries)

        if total_libs == 0:
            logger.warning(f"在 '{column_to_process}' 列中没有找到可处理的数据。")
            sys.exit(0)

        logger.info(f"在 '{column_to_process}' 列共找到 {total_libs} 个不重复的源库需要处理。")

        # 步骤 5: 循环处理所有不重复的库
        for i, library_name in enumerate(source_libraries):
            logger.info("=" * 70)
            logger.info(f"--> 正在处理第 {i + 1}/{total_libs} 个库: {library_name}")
            logger.info("=" * 70)

            ask(
                question=library_name,
                debug=debug_mode,
                max_plan_iterations=plan_iterations,
                max_step_num=step_num,
                enable_background_investigation=background_investigation,
            )
            logger.success(f"<-- 已完成对 '{library_name}' 的处理。")

        logger.success("--- 所有批量任务处理完毕 ---")

    except FileNotFoundError:
        # 这一层捕获以防万一
        logger.error(f"错误: 文件 '{file_to_process}' 未找到。")
        sys.exit(1)
    except Exception as e:
        logger.error(f"在批量处理过程中发生意外错误: {e}")
        # 打印详细的错误追溯信息，方便调试
        logger.exception("详细错误信息:")
        sys.exit(1)
import pandas as pd
from pathlib import Path
from typing import List
import logging  # 强烈建议使用loguru或Python内置的logging库来记录信息
logger = logging.getLogger(__name__)

def load_and_prepare_candidates(source_library: str) -> List[str]:
    try:

        current_file_path = Path(__file__)

        project_root = current_file_path.parent.parent.parent
        excel_path = project_root / "recommend-output.xlsx"

        logger.info(f"'{excel_path}' ...")

        df = pd.read_excel(excel_path)

        filtered_df = df[df['fromLib'] == source_library]

        if filtered_df.empty:
            logger.info(f" '{source_library}' ")
            return []

        top_20_df = filtered_df.sort_values(by='confidence', ascending=False).head(20)

        if 'toLib' in top_20_df.columns:
            to_lib_list = top_20_df['toLib'].tolist()
            logger.info(f" '{source_library}'  {len(to_lib_list)} ")
            return to_lib_list
        else:
            logger.error("error")
            return []

    except FileNotFoundError:
        logger.info(f"'{excel_path}'")
        return []
    except Exception as e:
        logger.info(f"Excel: {e}")
        return []
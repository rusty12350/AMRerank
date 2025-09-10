import pandas as pd
import numpy as np
import itertools
import warnings
from fuzzywuzzy import fuzz
from sklearn.preprocessing import MinMaxScaler

# --- 1. 核心配置区 (在此处修改你的文件和参数) ---

# 输入文件
BASE_LIBRARIES_FILE = 'merged_libraries.xlsx'
NUMERICAL_FEATURES_FILE = 'recommend-output.xlsx'
SEMANTIC_SCORES_FILE = 'dual_semantic_scores.csv'
GROUND_TRUTH_FILE = 'ground_truth.xlsx'
LABEL_SUPPORT_FILE = 'labelSupportAll.xlsx'

# 输出文件
RESULTS_OUTPUT_FILE = 'hybrid_exhaustive_experiment_results_with_mrr.csv'

# 混合排序阈值
SCORE_THRESHOLD = 3

# 【核心】可自定义的特征权重 (重要性)
FEATURE_WEIGHTS = {
    'commitMessageSupport': 221,
    'semantic_desc_score': 158,
    'semantic_name_score': 116,
    'apiSupportMin': 152,
    'ruleFreqSameCommit': 593,
    'commitDistance': 296,
    'fuzzy_score': 522,
    'label_similarity_count': 94,
}

# 决定要进行实验的所有特征的列表
ALL_FEATURES = list(FEATURE_WEIGHTS.keys())


# --- 2. 【核心修改点 1】扩展评估函数以包含 MRR ---
def calculate_metrics(df_ranked, ground_truth_map):
    """
    对一个已经排好序的DataFrame，计算 P@1, R@3, 和 MRR。
    """
    recommendation_groups = df_ranked.groupby('fromLib')
    libs_with_truth = [lib for lib in recommendation_groups.groups.keys() if
                       lib in ground_truth_map and len(ground_truth_map.get(lib, set())) > 0]
    total_groups_with_truth = len(libs_with_truth)

    if total_groups_with_truth == 0:
        return 0, 0, 0

    p1_correct_count = 0
    recall_at_3_scores = []
    mrr_scores = []  # 新增 MRR 分数列表

    for from_lib in libs_with_truth:
        group = recommendation_groups.get_group(from_lib)
        true_set = ground_truth_map[from_lib]
        num_true_items = len(true_set)

        # P@1
        if not group.empty and group['toLib'].iloc[0] in true_set:
            p1_correct_count += 1

        # R@3
        top_3_recs = set(group['toLib'].head(3))
        recall_at_3_scores.append(len(top_3_recs.intersection(true_set)) / num_true_items)

        # MRR
        rank = 0
        for i, recommended_lib in enumerate(group['toLib']):
            if recommended_lib in true_set:
                rank = i + 1  # 排名从1开始
                break
        mrr_scores.append(1 / rank if rank > 0 else 0)

    precision_at_1 = p1_correct_count / total_groups_with_truth
    avg_recall_at_3 = np.mean(recall_at_3_scores) if recall_at_3_scores else 0
    mrr = np.mean(mrr_scores) if mrr_scores else 0

    return precision_at_1, avg_recall_at_3, mrr


# --- 3. 主执行函数 ---

def run_combined_experiments():
    """
    主函数，执行数据加载、预处理、混合排序实验和评估。
    """
    print("--- 步骤 1: 加载所有数据文件 ---")
    try:
        df_base = pd.read_excel(BASE_LIBRARIES_FILE)
        df_numerical = pd.read_excel(NUMERICAL_FEATURES_FILE)
        df_semantic = pd.read_csv(SEMANTIC_SCORES_FILE)
        df_truth = pd.read_excel(GROUND_TRUTH_FILE)
        if 'label_similarity_count' in ALL_FEATURES:
            df_label_support = pd.read_excel(LABEL_SUPPORT_FILE)
        print("✅ 所有输入文件加载成功！")
    except FileNotFoundError as e:
        print(f"❌ 致命错误: 文件未找到 - {e}。脚本终止。")
        return

    print("\n--- 步骤 2: 数据预处理与合并 ---")
    merge_on = ['fromLib', 'toLib']
    numerical_features_needed = [f for f in ALL_FEATURES if f in df_numerical.columns]
    semantic_features_needed = [f for f in ALL_FEATURES if f in df_semantic.columns]

    df_numerical_subset = df_numerical[merge_on + numerical_features_needed].drop_duplicates(subset=merge_on)
    df_semantic_subset = df_semantic[merge_on + semantic_features_needed].drop_duplicates(subset=merge_on)

    df_merged = pd.merge(df_base, df_numerical_subset, on=merge_on, how='left')
    df_merged = pd.merge(df_merged, df_semantic_subset, on=merge_on, how='left')

    if 'fuzzy_score' in ALL_FEATURES and 'fuzzy_score' not in df_merged.columns:
        print("⏳ 正在计算 'fuzzy_score'...")
        df_merged['fuzzy_score'] = df_merged.apply(lambda r: fuzz.token_set_ratio(r['fromLib'], r['toLib']), axis=1)

    if 'label_similarity_count' in ALL_FEATURES and 'label_similarity_count' not in df_merged.columns:
        print("⏳ 正在计算 'label_similarity_count'...")
        df_label_support['label_similarity_count'] = df_label_support['labelSupport'].apply(
            lambda x: 0 if x == 1 else x / 5)
        df_merged = pd.merge(df_merged, df_label_support[merge_on + ['label_similarity_count']], on=merge_on,
                             how='left')

    features_in_df = [f for f in ALL_FEATURES if f in df_merged.columns]
    df_merged[features_in_df] = df_merged[features_in_df].fillna(0)

    print("⏳ 正在对所有特征进行归一化处理...")
    for col in features_in_df:
        min_val, max_val = df_merged[col].min(), df_merged[col].max()
        norm_col_name = f'{col}_norm'
        df_merged[norm_col_name] = (df_merged[col] - min_val) / (max_val - min_val) if max_val > min_val else 0

    ground_truth_map = df_truth[df_truth['isConfirmed'] == True].groupby('fromLib')['toLib'].apply(set).to_dict()
    print("✅ 数据准备完毕！")

    print("\n--- 步骤 3: 拆分数据并预排序高分库 ---")
    df_high_score = df_merged[df_merged['score'] > SCORE_THRESHOLD].copy()
    df_low_score = df_merged[df_merged['score'] <= SCORE_THRESHOLD].copy()

    df_high_score['formula_score'] = np.nan
    df_high_score_sorted = df_high_score.sort_values(by='score', ascending=False, kind='mergesort')
    print(f"高分库 ({len(df_high_score)}) 已按原始 'score' 排序。")
    print(f"低分库 ({len(df_low_score)}) 将进行组合实验。")

    print("\n--- 步骤 4: 开始对低分库进行全量特征组合实验 ---")
    results = []

    for k in range(1, len(ALL_FEATURES) + 1):
        for feature_combination in itertools.combinations(ALL_FEATURES, k):
            features_to_use = list(feature_combination)
            print(f"\n🔬 正在评测组合 (共{k}个特征): {', '.join(features_to_use)}")

            current_weights = {f: FEATURE_WEIGHTS[f] for f in features_to_use}
            total_weight = sum(current_weights.values())
            weights = {f: w / total_weight for f, w in current_weights.items()}
            df_low_score_temp = df_low_score.copy()

            # --- 模型 A: 加权和 (Additive) ---
            df_low_score_temp['formula_score'] = sum(df_low_score_temp[f'{f}_norm'] * w for f, w in weights.items())
            df_low_score_sorted_add = df_low_score_temp.sort_values(by='formula_score', ascending=False)
            df_final_ranked_add = pd.concat([df_high_score_sorted, df_low_score_sorted_add])

            # 【核心修改点 2】接收并存储新的 MRR 指标
            p1_add, r3_add, mrr_add = calculate_metrics(df_final_ranked_add, ground_truth_map)
            combo_name = f"Combo-{k}: " + ", ".join(features_to_use)
            results.append({'Method': combo_name, 'Model': 'Additive', 'P@1': p1_add, 'R@3': r3_add, 'MRR': mrr_add})

            # --- 模型 B: 加权积 (Multiplicative) ---
            epsilon = 1e-9
            df_low_score_temp['formula_score'] = 1.0
            for feature, weight in weights.items():
                df_low_score_temp['formula_score'] *= np.power(df_low_score_temp[f'{feature}_norm'] + epsilon, weight)

            df_low_score_sorted_mul = df_low_score_temp.sort_values(by='formula_score', ascending=False)
            df_final_ranked_mul = pd.concat([df_high_score_sorted, df_low_score_sorted_mul])

            p1_mul, r3_mul, mrr_mul = calculate_metrics(df_final_ranked_mul, ground_truth_map)
            results.append(
                {'Method': combo_name, 'Model': 'Multiplicative', 'P@1': p1_mul, 'R@3': r3_mul, 'MRR': mrr_mul})

    print("\n\n--- 步骤 5: 汇总并展示最终评测结果 ---")
    results_df = pd.DataFrame(results)
    results_df.sort_values(by='P@1', ascending=False, inplace=True)

    # --- 【核心修改点 3】调整最终输出以包含 MRR ---
    display_df = results_df.copy()
    display_df['P@1'] = display_df['P@1'].map('{:.2%}'.format)
    display_df['R@3'] = display_df['R@3'].map('{:.2%}'.format)
    display_df['MRR'] = display_df['MRR'].map('{:.4f}'.format)

    # 调整列顺序
    display_df = display_df[['Method', 'Model', 'P@1', 'R@3', 'MRR']]

    print("--- 实验结果 (按Precision@1从高到低排序) ---")
    print(display_df.to_string(index=False))

    try:
        results_df[['Method', 'Model', 'P@1', 'R@3', 'MRR']].to_csv(RESULTS_OUTPUT_FILE, index=False,
                                                                    encoding='utf-8-sig')
        print(f"\n✅ 完整的实验结果已成功保存至: '{RESULTS_OUTPUT_FILE}'")
    except Exception as e:
        print(f"\n❌ 保存结果文件时发生错误: {e}")

    print("\n--- 所有实验执行完毕 ---")


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
    run_combined_experiments()
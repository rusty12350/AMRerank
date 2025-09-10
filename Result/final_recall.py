import pandas as pd
import numpy as np

# --- 1. 特征重要性定义 ---
FEATURE_IMPORTANCES = {
    'commitMessageSupport': 221,
    'semantic_desc_score': 158,
    'semantic_name_score': 116,
    'apiSupportMin': 152,
}

# --- 2. 【核心修改点 1】扩展评估函数以包含 R@5 和 R@10 ---
def calculate_metrics(df_ranked, ground_truth_map, group_by_col, to_lib_col):
    """
    计算给定排序结果的 Precision@1, Recall@3, Recall@5, Recall@10。
    """
    libs_with_truth = [lib for lib in df_ranked[group_by_col].unique() if
                       lib in ground_truth_map and len(ground_truth_map[lib]) > 0]
    total_groups_with_truth = len(libs_with_truth)
    if total_groups_with_truth == 0:
        print("警告: 在测试集中没有找到任何与ground_truth匹配的推荐组。")
        return 0, 0, 0, 0

    p1_correct_count = 0
    recall_at_3_scores = []
    recall_at_5_scores = []
    recall_at_10_scores = []

    for from_lib in libs_with_truth:
        group = df_ranked[df_ranked[group_by_col] == from_lib]
        true_set = ground_truth_map[from_lib]
        num_true_items = len(true_set)

        group_sorted = group.sort_values(by=['score', 'formula_score'], ascending=[False, False], kind='mergesort')

        if not group_sorted.empty and group_sorted.iloc[0][to_lib_col] in true_set:
            p1_correct_count += 1

        # 同时计算 @3, @5, @10
        top_3_recs = set(group_sorted.head(3)[to_lib_col])
        top_5_recs = set(group_sorted.head(5)[to_lib_col])
        top_10_recs = set(group_sorted.head(10)[to_lib_col])

        recall_3 = len(top_3_recs.intersection(true_set)) / num_true_items
        recall_5 = len(top_5_recs.intersection(true_set)) / num_true_items
        recall_10 = len(top_10_recs.intersection(true_set)) / num_true_items

        recall_at_3_scores.append(recall_3)
        recall_at_5_scores.append(recall_5)
        recall_at_10_scores.append(recall_10)

    precision_at_1 = p1_correct_count / total_groups_with_truth
    avg_recall_at_3 = np.mean(recall_at_3_scores) if recall_at_3_scores else 0
    avg_recall_at_5 = np.mean(recall_at_5_scores) if recall_at_5_scores else 0
    avg_recall_at_10 = np.mean(recall_at_10_scores) if recall_at_10_scores else 0

    return precision_at_1, avg_recall_at_3, avg_recall_at_5, avg_recall_at_10


def run_and_evaluate_strategy(strategy_name, features_to_use, df_base, df_cms, df_semantic, df_truth):
    """
    根据指定的策略（特征和权重），执行完整的排序、评估流程。
    """
    print(f"\n\n{'=' * 20} 正在执行策略: {strategy_name} {'=' * 20}")
    print(f"使用的特征: {features_to_use}")

    # --- 参数配置 ---
    merge_on_columns = ['fromLib', 'toLib']
    group_by_column = 'fromLib'
    original_score_col = 'score'
    new_score_col_name = 'formula_score'
    output_file = f'final_ranked_results_{strategy_name}.xlsx'

    # --- 动态合并数据 ---
    print("\n--- 步骤 1/4: 动态合并数据文件 ---")
    cms_features_needed = [f for f in features_to_use if f in df_cms.columns]
    semantic_features_needed = [f for f in features_to_use if f in df_semantic.columns]

    df_cms_subset = df_cms[[*merge_on_columns] + cms_features_needed].drop_duplicates(subset=merge_on_columns)
    df_semantic_subset = df_semantic[[*merge_on_columns] + semantic_features_needed].drop_duplicates(
        subset=merge_on_columns)

    df_merged = pd.merge(df_base, df_cms_subset, on=merge_on_columns, how='left')
    df_merged = pd.merge(df_merged, df_semantic_subset, on=merge_on_columns, how='left')

    for feature in features_to_use:
        if feature not in df_merged.columns:
            print(f"致命错误: 特征 '{feature}' 在任何源文件中都找不到。")
            return
    print("数据合并成功。")

    # --- 混合排序逻辑 ---
    print("--- 步骤 2/4: 执行混合排序逻辑 ---")
    for col in features_to_use:
        min_val, max_val = df_merged[col].min(), df_merged[col].max()
        df_merged[f'{col}_norm'] = (df_merged[col] - min_val) / (max_val - min_val) if max_val > min_val else 0

    df_high_score = df_merged[df_merged[original_score_col] > 3].copy()
    df_low_score = df_merged[df_merged[original_score_col] <= 3].copy()

    df_high_score[new_score_col_name] = np.nan
    df_high_score_sorted = df_high_score.sort_values(by=original_score_col, ascending=False, kind='mergesort')

    if not df_low_score.empty:
        current_importances = {f: FEATURE_IMPORTANCES[f] for f in features_to_use}
        total_importance = sum(current_importances.values())
        weights = {f: imp / total_importance for f, imp in current_importances.items()}
        print(f"动态计算的权重: {weights}")

        epsilon = 1e-9
        df_low_score[new_score_col_name] = 1.0
        for feature, weight in weights.items():
            df_low_score[new_score_col_name] *= np.power(df_low_score[f'{feature}_norm'] + epsilon, weight)

        df_low_score_sorted = df_low_score.sort_values(by=new_score_col_name, ascending=False)
    else:
        df_low_score_sorted = pd.DataFrame(columns=df_high_score_sorted.columns)

    df_final_ranked = pd.concat([df_high_score_sorted, df_low_score_sorted], ignore_index=True)

    # --- 3. 【核心修改点 2】性能评估 ---
    print("--- 步骤 3/4: 计算所有指标 ---")
    ground_truth_map = df_truth[df_truth['isConfirmed'] == True].groupby(group_by_column)[merge_on_columns[1]].apply(
        set).to_dict()

    p1, r3, r5, r10 = calculate_metrics(df_final_ranked, ground_truth_map, group_by_column, merge_on_columns[1])

    print("\n---------- 策略评估结果 ----------")
    print(f"  策略名称: {strategy_name}")
    print(f"  Precision@1: {p1:.2%}")
    print(f"  Recall@3:    {r3:.2%}")
    print(f"  Recall@5:    {r5:.2%}")
    print(f"  Recall@10:   {r10:.2%}")
    print("----------------------------------")

    # --- 4. 保存文件 ---
    print(f"--- 步骤 4/4: 保存最终排序文件 ---")
    df_final_ranked.to_excel(output_file, index=False)
    print(f"处理完成！结果已保存到: {output_file}")


def main():
    """
    主执行函数：加载数据 -> 定义并执行多个策略 -> 输出结果
    """
    print("--- 准备阶段: 加载所有数据文件 ---")
    try:
        df_base = pd.read_excel('merged_libraries.xlsx')
        df_cms = pd.read_excel('recommend-output.xlsx')
        df_semantic = pd.read_csv('dual_semantic_scores.csv')
        df_truth = pd.read_excel('ground_truth.xlsx')
        print("所有文件加载成功。")
    except FileNotFoundError as e:
        print(f"错误: 文件未找到 - {e}。")
        return

    # --- 定义策略并执行 ---
    strategy_precision = {
        'name': 'Highest_Precision',
        'features': ['commitMessageSupport', 'semantic_desc_score', 'semantic_name_score']
    }
    run_and_evaluate_strategy(strategy_precision['name'], strategy_precision['features'], df_base, df_cms, df_semantic,
                              df_truth)

    strategy_recall = {
        'name': 'Highest_Recall',
        'features': ['commitMessageSupport', 'semantic_desc_score', 'apiSupportMin', 'semantic_name_score']
    }
    run_and_evaluate_strategy(strategy_recall['name'], strategy_recall['features'], df_base, df_cms, df_semantic,
                              df_truth)

    print("\n\n--- 所有策略执行完毕 ---")


if __name__ == '__main__':
    main()
import pandas as pd
import numpy as np
import itertools
import warnings
from fuzzywuzzy import fuzz
from sklearn.preprocessing import MinMaxScaler




BASE_LIBRARIES_FILE = 'merged_libraries.xlsx'
NUMERICAL_FEATURES_FILE = 'recommend-output.xlsx'
SEMANTIC_SCORES_FILE = 'dual_semantic_scores.csv'
GROUND_TRUTH_FILE = 'ground_truth.xlsx'
LABEL_SUPPORT_FILE = 'labelSupportAll.xlsx'


RESULTS_OUTPUT_FILE = 'hybrid_exhaustive_experiment_results_with_mrr.csv'


SCORE_THRESHOLD = 3


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


ALL_FEATURES = list(FEATURE_WEIGHTS.keys())



def calculate_metrics(df_ranked, ground_truth_map):

    recommendation_groups = df_ranked.groupby('fromLib')
    libs_with_truth = [lib for lib in recommendation_groups.groups.keys() if
                       lib in ground_truth_map and len(ground_truth_map.get(lib, set())) > 0]
    total_groups_with_truth = len(libs_with_truth)

    if total_groups_with_truth == 0:
        return 0, 0, 0

    p1_correct_count = 0
    recall_at_3_scores = []
    mrr_scores = [] 

    for from_lib in libs_with_truth:
        group = recommendation_groups.get_group(from_lib)
        true_set = ground_truth_map[from_lib]
        num_true_items = len(true_set)


        if not group.empty and group['toLib'].iloc[0] in true_set:
            p1_correct_count += 1

 
        top_3_recs = set(group['toLib'].head(3))
        recall_at_3_scores.append(len(top_3_recs.intersection(true_set)) / num_true_items)

       
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




def run_combined_experiments():


    try:
        df_base = pd.read_excel(BASE_LIBRARIES_FILE)
        df_numerical = pd.read_excel(NUMERICAL_FEATURES_FILE)
        df_semantic = pd.read_csv(SEMANTIC_SCORES_FILE)
        df_truth = pd.read_excel(GROUND_TRUTH_FILE)
        if 'label_similarity_count' in ALL_FEATURES:
            df_label_support = pd.read_excel(LABEL_SUPPORT_FILE)

    except FileNotFoundError as e:
        print(f"❌ {e} ")
        return


    merge_on = ['fromLib', 'toLib']
    numerical_features_needed = [f for f in ALL_FEATURES if f in df_numerical.columns]
    semantic_features_needed = [f for f in ALL_FEATURES if f in df_semantic.columns]

    df_numerical_subset = df_numerical[merge_on + numerical_features_needed].drop_duplicates(subset=merge_on)
    df_semantic_subset = df_semantic[merge_on + semantic_features_needed].drop_duplicates(subset=merge_on)

    df_merged = pd.merge(df_base, df_numerical_subset, on=merge_on, how='left')
    df_merged = pd.merge(df_merged, df_semantic_subset, on=merge_on, how='left')

    if 'fuzzy_score' in ALL_FEATURES and 'fuzzy_score' not in df_merged.columns:
        print("⏳  'fuzzy_score'...")
        df_merged['fuzzy_score'] = df_merged.apply(lambda r: fuzz.token_set_ratio(r['fromLib'], r['toLib']), axis=1)

    if 'label_similarity_count' in ALL_FEATURES and 'label_similarity_count' not in df_merged.columns:
        print("⏳  'label_similarity_count'...")
        df_label_support['label_similarity_count'] = df_label_support['labelSupport'].apply(
            lambda x: 0 if x == 1 else x / 5)
        df_merged = pd.merge(df_merged, df_label_support[merge_on + ['label_similarity_count']], on=merge_on,
                             how='left')

    features_in_df = [f for f in ALL_FEATURES if f in df_merged.columns]
    df_merged[features_in_df] = df_merged[features_in_df].fillna(0)

    print("⏳ ...")
    for col in features_in_df:
        min_val, max_val = df_merged[col].min(), df_merged[col].max()
        norm_col_name = f'{col}_norm'
        df_merged[norm_col_name] = (df_merged[col] - min_val) / (max_val - min_val) if max_val > min_val else 0

    ground_truth_map = df_truth[df_truth['isConfirmed'] == True].groupby('fromLib')['toLib'].apply(set).to_dict()
    print("✅ ！")


    df_high_score = df_merged[df_merged['score'] > SCORE_THRESHOLD].copy()
    df_low_score = df_merged[df_merged['score'] <= SCORE_THRESHOLD].copy()

    df_high_score['formula_score'] = np.nan
    df_high_score_sorted = df_high_score.sort_values(by='score', ascending=False, kind='mergesort')
    results = []

    for k in range(1, len(ALL_FEATURES) + 1):
        for feature_combination in itertools.combinations(ALL_FEATURES, k):
            features_to_use = list(feature_combination)
            print(f"\n🔬  {k}: {', '.join(features_to_use)}")

            current_weights = {f: FEATURE_WEIGHTS[f] for f in features_to_use}
            total_weight = sum(current_weights.values())
            weights = {f: w / total_weight for f, w in current_weights.items()}
            df_low_score_temp = df_low_score.copy()


            df_low_score_temp['formula_score'] = sum(df_low_score_temp[f'{f}_norm'] * w for f, w in weights.items())
            df_low_score_sorted_add = df_low_score_temp.sort_values(by='formula_score', ascending=False)
            df_final_ranked_add = pd.concat([df_high_score_sorted, df_low_score_sorted_add])


            p1_add, r3_add, mrr_add = calculate_metrics(df_final_ranked_add, ground_truth_map)
            combo_name = f"Combo-{k}: " + ", ".join(features_to_use)
            results.append({'Method': combo_name, 'Model': 'Additive', 'P@1': p1_add, 'R@3': r3_add, 'MRR': mrr_add})


            epsilon = 1e-9
            df_low_score_temp['formula_score'] = 1.0
            for feature, weight in weights.items():
                df_low_score_temp['formula_score'] *= np.power(df_low_score_temp[f'{feature}_norm'] + epsilon, weight)

            df_low_score_sorted_mul = df_low_score_temp.sort_values(by='formula_score', ascending=False)
            df_final_ranked_mul = pd.concat([df_high_score_sorted, df_low_score_sorted_mul])

            p1_mul, r3_mul, mrr_mul = calculate_metrics(df_final_ranked_mul, ground_truth_map)
            results.append(
                {'Method': combo_name, 'Model': 'Multiplicative', 'P@1': p1_mul, 'R@3': r3_mul, 'MRR': mrr_mul})


    results_df = pd.DataFrame(results)
    results_df.sort_values(by='P@1', ascending=False, inplace=True)


    display_df = results_df.copy()
    display_df['P@1'] = display_df['P@1'].map('{:.2%}'.format)
    display_df['R@3'] = display_df['R@3'].map('{:.2%}'.format)
    display_df['MRR'] = display_df['MRR'].map('{:.4f}'.format)


    display_df = display_df[['Method', 'Model', 'P@1', 'R@3', 'MRR']]


    print(display_df.to_string(index=False))

    try:
        results_df[['Method', 'Model', 'P@1', 'R@3', 'MRR']].to_csv(RESULTS_OUTPUT_FILE, index=False,
                                                                    encoding='utf-8-sig')
        print(f"\n✅ : '{RESULTS_OUTPUT_FILE}'")
    except Exception as e:
        print(f"\n❌ : {e}")




if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
    run_combined_experiments()

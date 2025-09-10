import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from fuzzywuzzy import fuzz
import warnings
import itertools


warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")


LOW_SCORE_FILE = 'difficult_cases_score_3.csv'
GROUND_TRUTH_FILE = 'ground_truth.xlsx'
NUMERICAL_FEATURES_FILE = 'recommend-output.xlsx'
SEMANTIC_SCORES_FILE = 'dual_semantic_scores.csv'

RESULTS_OUTPUT_FILE = 'full_experiment_results_with_recall3.csv'


FEATURE_IMPORTANCES = {
    'ruleFreqSameCommit': 593,
    'fuzzy_score': 522,
    'commitDistance': 296,
    'commitMessageSupport': 221,
    'semantic_desc_score': 158,
    'apiSupportMin': 152,
    'semantic_name_score': 116,
}
ALL_FEATURES = list(FEATURE_IMPORTANCES.keys())


def load_and_prepare_data():
    try:
        df_low_score = pd.read_csv(LOW_SCORE_FILE, encoding='utf-8')
        df_gt = pd.read_excel(GROUND_TRUTH_FILE, sheet_name='Sheet2')
        df_numerical = pd.read_excel(NUMERICAL_FEATURES_FILE)
        df_semantic = pd.read_csv(SEMANTIC_SCORES_FILE)
        print("✅ ")
    except Exception as e:
        print(f"❌")
        return None, None

    if 'source_library' in df_low_score.columns:
        df_low_score.rename(columns={'source_library': 'fromLib', 'predicted_target_library': 'toLib'}, inplace=True)

    print("⏳")
    df_low_score['fuzzy_score'] = df_low_score.apply(
        lambda row: fuzz.token_set_ratio(row['fromLib'], row['toLib']), axis=1
    )

    print("⏳")
    features_from_numerical = [f for f in ALL_FEATURES if f in df_numerical.columns]
    df_master = pd.merge(df_low_score, df_numerical[['fromLib', 'toLib'] + features_from_numerical],
                         on=['fromLib', 'toLib'], how='left')

    if {'semantic_desc_score', 'semantic_name_score'}.issubset(df_semantic.columns):
        df_master = pd.merge(df_master, df_semantic[['fromLib', 'toLib', 'semantic_desc_score', 'semantic_name_score']],
                             on=['fromLib', 'toLib'], how='left')
    df_master[ALL_FEATURES] = df_master[ALL_FEATURES].fillna(0)

    print("⏳")
    scaler = MinMaxScaler()
    df_master[ALL_FEATURES] = scaler.fit_transform(df_master[ALL_FEATURES])

    ground_truth_map = df_gt[df_gt['isConfirmed'] == True].groupby('fromLib')['toLib'].apply(set).to_dict()
    print("✅")
    return df_master, ground_truth_map



def calculate_metrics(df_to_evaluate, score_column, ground_truth_map):

    df_sorted = df_to_evaluate.sort_values(by=['fromLib', score_column], ascending=[True, False])
    recommendation_groups = df_sorted.groupby('fromLib')

    libs_with_truth = [lib for lib in recommendation_groups.groups.keys() if lib in ground_truth_map and len(ground_truth_map[lib]) > 0]
    total_groups_with_truth = len(libs_with_truth)
    if total_groups_with_truth == 0:
        return 0, 0, 0, 0

    p1_correct_count = 0
    recall_at_3_scores = []

    for from_lib in libs_with_truth:
        group = recommendation_groups.get_group(from_lib)
        true_set = ground_truth_map[from_lib]
        num_true_items = len(true_set)

        # Precision@1
        if group['toLib'].iloc[0] in true_set:
            p1_correct_count += 1

        # Recall@3
        top_3_recs = set(group['toLib'].head(3))
        recall_3 = len(top_3_recs.intersection(true_set)) / num_true_items
        recall_at_3_scores.append(recall_3)

    precision_at_1 = p1_correct_count / total_groups_with_truth
    avg_recall_at_3 = np.mean(recall_at_3_scores) if recall_at_3_scores else 0

    return precision_at_1, avg_recall_at_3, p1_correct_count, total_groups_with_truth


def run_experiments():

    df_master, ground_truth_map = load_and_prepare_data()
    if df_master is None: return
    results = []
    for k in range(1, len(ALL_FEATURES) + 1):
        for feature_combination in itertools.combinations(ALL_FEATURES, k):
            features_to_use = list(feature_combination)
            print(f"\n🔬({len(features_to_use)}): {', '.join(features_to_use)}")
            if len(features_to_use) == 1:
                method_name = f"Single: {features_to_use[0]}"
                score_col = features_to_use[0]
                p1, r3, c1, total = calculate_metrics(df_master.copy(), score_col, ground_truth_map)
                results.append({'Method': method_name, 'Correct@1': c1, 'Total': total,
                                'Precision@1': p1, 'Recall@3': r3})
                continue

            current_importances = {f: FEATURE_IMPORTANCES[f] for f in features_to_use}
            total_importance = sum(current_importances.values())
            weights = {f: imp / total_importance for f, imp in current_importances.items()}
            combo_name = f"Combo-{k}: " + ", ".join(features_to_use)

            score_col_add = 'additive_score'
            df_master[score_col_add] = sum(df_master[feature] * weight for feature, weight in weights.items())
            p1_add, r3_add, c1_add, total_add = calculate_metrics(df_master.copy(), score_col_add, ground_truth_map)
            results.append({'Method': f"{combo_name} (Add)", 'Correct@1': c1_add, 'Total': total_add,
                            'Precision@1': p1_add, 'Recall@3': r3_add})

            score_col_mul = 'multiplicative_score'
            epsilon = 1e-9
            df_master[score_col_mul] = 1.0
            for feature, weight in weights.items():
                df_master[score_col_mul] *= np.power(df_master[feature] + epsilon, weight)
            p1_mul, r3_mul, c1_mul, total_mul = calculate_metrics(df_master.copy(), score_col_mul, ground_truth_map)
            results.append({'Method': f"{combo_name} (Mul)", 'Correct@1': c1_mul, 'Total': total_mul,
                            'Precision@1': p1_mul, 'Recall@3': r3_mul})


    print("\n\n---P@1---")
    results_df = pd.DataFrame(results)
    results_df.sort_values(by='Precision@1', ascending=False, inplace=True)

    display_df = results_df.copy()
    column_order = ['Method', 'Correct@1', 'Total', 'Precision@1', 'Recall@3']
    display_df = display_df[column_order]

    display_df['Precision@1'] = display_df['Precision@1'].map('{:.2%}'.format)
    display_df['Recall@3'] = display_df['Recall@3'].map('{:.2%}'.format)

    print(display_df.to_string(index=False))

    try:
        results_df[column_order].to_csv(RESULTS_OUTPUT_FILE, index=False, encoding='utf-8-sig')
        print(f"\n\n✅'{RESULTS_OUTPUT_FILE}'")
    except Exception as e:
        print(f"\n\n❌  {e}")

    print("\n------")


if __name__ == "__main__":
    run_experiments()
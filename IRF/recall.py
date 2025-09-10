import pandas as pd
import os
from fuzzywuzzy import fuzz
import lightgbm as lgb
from sklearn.model_selection import GroupShuffleSplit
import matplotlib.pyplot as plt
import seaborn as sns
import joblib


numerical_features_file = 'recommend-output.xlsx'
full_experiment_file = 'experiment_results.csv'
semantic_scores_file = 'dual_semantic_scores.csv'
ground_truth_file = 'ground_truth.csv'


output_model_file = 'lgbm_ranker_optimized_model.joblib'
output_feature_importance_file = 'feature_importance_optimized.png'



def prepare_ultimate_data():
    print("--- 🚀 ---")

    try:
        df_main = pd.read_excel(numerical_features_file)
        df_exp = pd.read_csv(full_experiment_file, encoding='utf-8-sig')
        df_semantic = pd.read_csv(semantic_scores_file, encoding='utf-8-sig')
        print("✅ ")
    except Exception as e:
        print(f"❌ {e}")
        return None


    print("⚙️  ...")
    df_main['fuzzy_score'] = df_main.apply(lambda row: fuzz.token_set_ratio(row['fromLib'], row['toLib']), axis=1)


    print("⚙️  ...")
    df_merged = pd.merge(df_main, df_exp[['source_library', 'predicted_target_library', 'relationship_type']],
                         how='left', left_on=['fromLib', 'toLib'],
                         right_on=['source_library', 'predicted_target_library'])
    df_merged = pd.merge(df_merged, df_semantic, how='left', on=['fromLib', 'toLib'])
    print("✅ ")


    print("🔬 ...")
    final_df = df_merged.copy()
    final_df['label'] = final_df['isConfirmed'].astype(int)
    final_df['relationship_type_cleaned'] = final_df['relationship_type'].str.lower().str.replace(r'[^a-z0-9]+', ' ',
                                                                                                  regex=True).str.replace(
        r'\s+', '_', regex=True).str.strip('_').fillna('unknown')
    dummies = pd.get_dummies(final_df['relationship_type_cleaned'], prefix='rel_type')
    final_df = pd.concat([final_df, dummies], axis=1)
    confidence_map = {'High': 3, 'Medium': 2, 'Low': 1}
    final_df['confidence_numeric'] = final_df['confidence'].map(confidence_map).fillna(0)

    final_df[['semantic_name_score', 'semantic_desc_score']] = final_df[
        ['semantic_name_score', 'semantic_desc_score']].fillna(0)
    print("✅ ")

    print("--- ✅ ---")
    return final_df



def train_and_evaluate(df: pd.DataFrame):

    print("\n--- 🚀---")

    df_sorted = df.sort_values(by='fromLib').reset_index(drop=True)

    rel_type_cols = [col for col in df_sorted.columns if col.startswith('rel_type_')]
    feature_columns = [
                          'score', 'confidence_numeric', 'fuzzy_score',
                          'semantic_name_score', 'semantic_desc_score',
                          'commitMessageSupport', 'commitDistance', 'ruleFreqSameCommit', 'apiSupportMin'
                      ] + rel_type_cols

    X = df_sorted[[col for col in feature_columns if col in df_sorted.columns]]
    y = df_sorted['label']
    print(f" {X.shape[1]}， {X.shape[0]}")

    group_sizes = df_sorted.groupby('fromLib').size().to_numpy()

    gs = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(gs.split(X, y, groups=df_sorted['fromLib']))

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    train_groups = df_sorted.iloc[train_idx].groupby('fromLib').size().to_numpy()
    test_groups_df = df_sorted.iloc[test_idx].copy()

    print("\n--- LGBMRanker  ---")
    ranker = lgb.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        n_estimators=1000,
        learning_rate=0.05,
        num_leaves=31,
        random_state=42
    )


    ranker.fit(X_train, y_train, group=train_groups, eval_set=[(X_test, y_test)],
               eval_group=[test_groups_df.groupby('fromLib').size().to_numpy()],
               eval_at=[1, 5, 10],
               callbacks=[lgb.early_stopping(50, verbose=True)])
    print("--- ✅  ---")


    joblib.dump(ranker, output_model_file)
    print(f"\n--- 💾 '{output_model_file}' ---")


    print("\n--- 📊  ---")
    test_groups_df['pred_score'] = ranker.predict(X_test)


    p1_correct_count = 0
    recall_at_5_scores = []
    recall_at_10_scores = []


    ground_truth_map = df[df['label'] == 1].groupby('fromLib')['toLib'].apply(set).to_dict()
    unique_from_libs_in_test = test_groups_df['fromLib'].unique()


    test_libs_with_truth = [lib for lib in unique_from_libs_in_test if
                            lib in ground_truth_map and len(ground_truth_map[lib]) > 0]
    total_test_groups_with_truth = len(test_libs_with_truth)

    for from_lib in test_libs_with_truth:

        group = test_groups_df[test_groups_df['fromLib'] == from_lib]
        top_k_recs = group.sort_values('pred_score', ascending=False)
        true_set = ground_truth_map[from_lib]
        num_true_items = len(true_set)


        top_1_rec_set = set(top_k_recs.head(1)['toLib'])
        top_5_recs_set = set(top_k_recs.head(5)['toLib'])
        top_10_recs_set = set(top_k_recs.head(10)['toLib'])



        if not top_1_rec_set.isdisjoint(true_set):
            p1_correct_count += 1


        recall_5 = len(top_5_recs_set.intersection(true_set)) / num_true_items
        recall_10 = len(top_10_recs_set.intersection(true_set)) / num_true_items
        recall_at_5_scores.append(recall_5)
        recall_at_10_scores.append(recall_10)


    precision_at_1 = p1_correct_count / total_test_groups_with_truth if total_test_groups_with_truth > 0 else 0
    avg_recall_at_5 = sum(recall_at_5_scores) / total_test_groups_with_truth if total_test_groups_with_truth > 0 else 0
    avg_recall_at_10 = sum(
        recall_at_10_scores) / total_test_groups_with_truth if total_test_groups_with_truth > 0 else 0

    print("\n====================")
    print(f"  Precision@1: {precision_at_1:.2%}")
    print(f"  Recall@5:    {avg_recall_at_5:.2%}")
    print(f"  Recall@10:   {avg_recall_at_10:.2%}")
    print("===================================")

    print("\n--- 🧠  ---")
    feature_importances = pd.DataFrame({'feature': X.columns, 'importance': ranker.feature_importances_}).sort_values(
        'importance', ascending=False)
    print(feature_importances.head(20))

    plt.figure(figsize=(12, 10))
    sns.barplot(x='importance', y='feature', data=feature_importances.head(20))
    plt.title('Top 20 Feature Importances (Optimized Ranker Model)')
    plt.tight_layout()
    plt.savefig(output_feature_importance_file)
    print(f"\n✅: '{output_feature_importance_file}'")



if __name__ == "__main__":
    final_data = prepare_ultimate_data()
    if final_data is not None:
        train_and_evaluate(final_data)
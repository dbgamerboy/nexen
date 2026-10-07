# ==============================================================================
# NEXEN FINAL - MARVIN WORKFLOW ROI & SUCCESS CALCULATOR (THE GOLDEN MATH)
# ==============================================================================

class WorkflowEvaluator:
    def __init__(self):
        self.minimum_viable_roi = 20.0 # Require at least 20% ROI to keep a workflow alive

    def calculate_success(self, workflow_name, money_earned, money_spent, repeatability_1_to_10, execution_time_hours):
        print(f"\n[EVALUATING WORKFLOW]: {workflow_name}")
        
        profit = money_earned - money_spent
        
        if money_spent == 0:
            roi_percentage = float('inf') if profit > 0 else 0.0
        else:
            roi_percentage = (profit / money_spent) * 100

        if profit <= 0:
            print(f"-> [KILL COMMAND] {workflow_name} is operating at a loss. Margin: . TERMINATING.")
            return 0.0
            
        # The Golden Math: Profit scaled by how easily the machine can repeat it without human input.
        time_factor = execution_time_hours if execution_time_hours > 0 else 0.1
        success_score = (profit * (repeatability_1_to_10 / 10)) / time_factor
        
        print(f"-> Money Earned:  | Spent:  | Profit: ")
        print(f"-> ROI: {roi_percentage}% | Repeatability: {repeatability_1_to_10}/10")
        print(f"-> FINAL SUCCESS SCORE: {success_score:.2f}")
        
        if roi_percentage >= self.minimum_viable_roi:
            print(f"-> [SCALE COMMAND] Workflow is highly profitable and repeatable. SCALING RESOURCES.")
        else:
            print(f"-> [HOLD COMMAND] Workflow is barely breaking even. Sent to backlog for optimization.")
            
        return success_score

evaluator = WorkflowEvaluator()
evaluator.calculate_success("Faceless TikTok Affiliate", money_earned=150.00, money_spent=2.50, repeatability_1_to_10=9, execution_time_hours=0.5)
evaluator.calculate_success("Broken Outreach Script", money_earned=10.00, money_spent=12.00, repeatability_1_to_10=5, execution_time_hours=2.0)

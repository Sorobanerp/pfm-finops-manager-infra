output "lambda_function_arn" {
  description = "ARN of the FinOps Manager Lambda function"
  value       = aws_lambda_function.finops_manager.arn
}

output "lambda_function_name" {
  description = "Name of the FinOps Manager Lambda function"
  value       = aws_lambda_function.finops_manager.function_name
}

output "park_schedule_arn" {
  description = "ARN of the nightly 20:30 BRT Park EventBridge schedule"
  value       = aws_scheduler_schedule.park_nightly_2030.arn
}

output "unpark_schedule_arn" {
  description = "ARN of the morning 06:00 BRT Unpark EventBridge schedule"
  value       = aws_scheduler_schedule.unpark_morning_0600.arn
}

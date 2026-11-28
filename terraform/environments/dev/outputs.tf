output "lambda_function_arn" {
  description = "ARN of the FinOps Manager Lambda function"
  value       = module.finops_manager.lambda_function_arn
}

output "lambda_function_name" {
  description = "Name of the FinOps Manager Lambda function"
  value       = module.finops_manager.lambda_function_name
}

output "park_schedule_arn" {
  description = "ARN of the nightly 20:30 BRT Park EventBridge schedule"
  value       = module.finops_manager.park_schedule_arn
}

output "unpark_schedule_arn" {
  description = "ARN of the morning 06:00 BRT Unpark EventBridge schedule"
  value       = module.finops_manager.unpark_schedule_arn
}

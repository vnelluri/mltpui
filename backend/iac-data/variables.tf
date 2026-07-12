variable "table_name" {
  description = "Name of the single DynamoDB table."
  type        = string
  default     = "ml-platform"
}

variable "tags" {
  description = "Tags applied to the table (Application is always set)."
  type        = map(string)
  default     = {}
}

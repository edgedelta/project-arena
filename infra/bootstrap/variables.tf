variable "region" {
  type        = string
  description = "AWS region supplied by the operator"
}

variable "state_bucket_name" {
  type = string
}
variable "lock_table_name" {
  type = string
}

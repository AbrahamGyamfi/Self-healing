variable "prefix" { type = string }
variable "sns_topic_arn" { type = string }
variable "asg_arn" {
  type    = string
  default = ""
}


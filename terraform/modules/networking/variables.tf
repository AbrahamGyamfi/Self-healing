variable "prefix"     { type = string }
variable "aws_region" { type = string }
variable "your_ip_cidr" {
  type    = string
  default = "0.0.0.0/0"
}
variable "alert_email" {
  type    = string
  default = ""
}

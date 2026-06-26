variable "prefix" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "sg_id" { type = string }
variable "instance_profile_arn" { type = string }
variable "ec2_instance_type" {
  type    = string
  default = "t3.small"
}
variable "asg_min_size" {
  type    = number
  default = 1
}
variable "asg_max_size" {
  type    = number
  default = 4
}
variable "asg_desired_capacity" {
  type    = number
  default = 1
}

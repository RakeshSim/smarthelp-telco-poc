variable "name" {
  description = "Layer name (also used as the build directory name)."
  type        = string
}

variable "requirements_path" {
  description = "Path to a requirements.txt file with the layer's pip dependencies."
  type        = string
}

variable "build_dir" {
  description = "Scratch directory Terraform uses to pip-install and zip the layer contents."
  type        = string
  default     = "build/layers"
}

variable "compatible_runtimes" {
  description = "Lambda runtimes this layer is compatible with."
  type        = list(string)
  default     = ["python3.12"]
}

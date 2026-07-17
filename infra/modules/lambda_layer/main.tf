# Builds a Lambda layer by pip-installing requirements.txt into a
# `python/` folder (the layout Lambda expects) and zipping it.
#
# We build the layer ourselves instead of using AWS's public Powertools
# layer ARN so the module has no hidden dependency on a specific region
# publishing a specific version — everything needed to reproduce the
# layer is checked into this repo.

locals {
  layer_build_path = "${path.root}/${var.build_dir}/${var.name}"
  python_dir       = "${local.layer_build_path}/python"
}

# terraform_data (the modern, provider-agnostic replacement for
# null_resource) re-runs its provisioner whenever requirements.txt changes,
# tracked via its content hash in `triggers_replace`.
resource "terraform_data" "install" {
  triggers_replace = {
    requirements_hash = filemd5(var.requirements_path)
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -euo pipefail
      rm -rf "${local.python_dir}"
      mkdir -p "${local.python_dir}"
      pip3 install -r "${var.requirements_path}" \
        --platform manylinux2014_x86_64 \
        --implementation cp \
        --python-version 3.12 \
        --only-binary=:all: \
        --target "${local.python_dir}"
    EOT
  }
}

# A data source that depends_on a not-yet-created resource is deferred to
# the apply phase, so this correctly zips the folder *after* pip install
# runs. Expect Terraform to show its contents as "(known after apply)"
# on a first `plan` — that's this pattern, not a bug.
data "archive_file" "layer_zip" {
  depends_on = [terraform_data.install]
  type       = "zip"
  # Zip the parent dir (not python_dir itself) so the archive's root
  # contains a "python/" folder — the layout Lambda requires to put
  # these packages on PYTHONPATH.
  source_dir  = local.layer_build_path
  output_path = "${local.layer_build_path}.zip"
}

resource "aws_lambda_layer_version" "this" {
  layer_name               = var.name
  filename                 = data.archive_file.layer_zip.output_path
  source_code_hash         = data.archive_file.layer_zip.output_base64sha256
  compatible_runtimes      = var.compatible_runtimes
  compatible_architectures = ["x86_64"]
}

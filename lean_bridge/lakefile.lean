import Lake
open Lake DSL

package «lean2md_bridge» where
  version := v!"1.0.0"

@[default_target]
lean_exe «lean2md-extractor» where
  root := `Lean2MdExtractor

/-!
# Lean2MdExtractor

Native Lean 4 elaboration extractor for Lean2Markdown.
Uses Lean 4's `Lean.Elab.Frontend` and `Lean.Meta` APIs to elaborate a `.lean` source file
and emit a JSON payload containing resolved declaration names, elaborated types,
and whether each declaration is a proposition (`Prop`).

Usage:
  `lean --run Lean2MdExtractor.lean <path/to/file.lean>`
-/
import Lean

open Lean Elab Frontend Meta

private def escapeJson (s : String) : String :=
  s.foldl (fun acc c =>
    match c with
    | '"'  => acc ++ "\\\""
    | '\\' => acc ++ "\\\\"
    | '\n' => acc ++ "\\n"
    | '\r' => acc ++ "\\r"
    | '\t' => acc ++ "\\t"
    | _    => acc.push c
  ) ""

private def declToJson (env : Environment) (name : Name) (cinfo : ConstantInfo) : IO String := do
  let typeStr := toString cinfo.type
  let isProp :=
    match cinfo with
    | .thmInfo _ => true
    | _          => false
  let kindStr :=
    match cinfo with
    | .thmInfo _    => "theorem"
    | .defnInfo _   => "def"
    | .axiomInfo _  => "axiom"
    | .opaqueInfo _ => "opaque"
    | .inductInfo _ => "inductive"
    | .ctorInfo _   => "constructor"
    | .recInfo _    => "recursor"
    | .quotInfo _   => "quot"
  let docStr :=
    match findDocString? env name with
    | some d => d
    | none   => ""
  pure <|
    "{\"name\":\"" ++ escapeJson name.toString ++
    "\",\"kind\":\"" ++ kindStr ++
    "\",\"isProp\":" ++ (if isProp then "true" else "false") ++
    ",\"type\":\"" ++ escapeJson typeStr ++
    "\",\"doc\":\"" ++ escapeJson docStr ++ "\"}"

def main (args : List String) : IO UInt32 := do
  match args with
  | [filePath] =>
    initSearchPath (← findSysroot)
    let input ← IO.FS.readFile filePath
    let opts := Options.empty
    let (env, ok) ← process input (← mkEmptyEnvironment) opts filePath
    let mut entries : Array String := #[]
    for (name, cinfo) in env.constants.map₂.toList do
      if !name.isInternal then
        let j ← declToJson env name cinfo
        entries := entries.push j
    let joined := String.intercalate "," entries.toList
    IO.println ("{\"ok\":" ++ (if ok then "true" else "false") ++ ",\"declarations\":[" ++ joined ++ "]}")
    return 0
  | _ =>
    IO.eprintln "Usage: lean --run Lean2MdExtractor.lean <file.lean>"
    return 1

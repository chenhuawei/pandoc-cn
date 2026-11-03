-- plantuml-filter.lua - PlantUML diagram filter for Pandoc 3.x

local function file_exists(path)
  local f = io.open(path, "r")
  if f then f:close() return true end
  return false
end

function CodeBlock(el)
  if el.classes[1] ~= "plantuml" then
    return nil
  end

  local tmpdir = "/tmp/pandoc-puml-" .. tostring(os.time()) .. tostring(math.random(1000))
  os.execute('mkdir -p "' .. tmpdir .. '"')

  local puml_path = tmpdir .. "/diagram.puml"
  local png_path = tmpdir .. "/diagram.png"

  -- Write plantuml source
  local f = io.open(puml_path, "w")
  if not f then return el end
  f:write(el.text)
  f:close()

  -- Run plantuml in the temp directory
  os.execute('cd "' .. tmpdir .. '" && plantuml -t png diagram.puml 2>/dev/null')

  if file_exists(png_path) then
    local b64f = io.popen('base64 "' .. png_path .. '"', "r")
    local b64 = ""
    if b64f then
      b64 = b64f:read("*a"):gsub("[\r\n]", "")
      b64f:close()
    end
    os.execute('rm -rf "' .. tmpdir .. '"')

    if #b64 > 0 then
      return pandoc.Para({
        pandoc.Image(
          {pandoc.Str("PlantUML Diagram")},
          "data:image/png;base64," .. b64
        )
      })
    end
  end

  os.execute('rm -rf "' .. tmpdir .. '"')
  return el
end

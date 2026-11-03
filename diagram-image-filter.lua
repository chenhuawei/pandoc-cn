-- diagram-image-filter.lua - Render draw.io, Mermaid, and PlantUML blocks to PNG.

local tmp_counter = 0

local function has_class(el, class)
  for _, c in ipairs(el.classes) do
    if c == class then
      return true
    end
  end
  return false
end

local function shell_quote(value)
  return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

local function file_exists(path)
  local f = io.open(path, "rb")
  if f then
    f:close()
    return true
  end
  return false
end

local function read_binary(path)
  local f = assert(io.open(path, "rb"), "cannot open generated image: " .. path)
  local data = f:read("*a")
  f:close()
  return data
end

local function write_text(path, text)
  local f = assert(io.open(path, "w"), "cannot write diagram source: " .. path)
  f:write(text)
  f:close()
end

local function mkdir(path)
  local ok = os.execute("mkdir -p " .. shell_quote(path))
  if ok ~= true and ok ~= 0 then
    error("cannot create temporary directory: " .. path)
  end
end

local function rmtree(path)
  os.execute("rm -rf " .. shell_quote(path))
end

local function tempdir(kind)
  tmp_counter = tmp_counter + 1
  local dir = string.format(
    "/tmp/pandoc-%s-%s-%d-%d",
    kind,
    tostring(os.time()),
    math.random(100000, 999999),
    tmp_counter
  )
  mkdir(dir)
  return dir
end

local function run(command)
  local ok = os.execute(command)
  return ok == true or ok == 0
end

local function render_to_mediabag(kind, source, extension, command_builder)
  local dir = tempdir(kind)
  local input = dir .. "/diagram." .. extension
  local output = dir .. "/diagram.png"
  local log = dir .. "/render.log"
  write_text(input, source)

  local command = command_builder(input, output, log)
  local ok = run(command)
  if not ok or not file_exists(output) then
    local details = ""
    if file_exists(log) then
      details = read_binary(log)
    end
    rmtree(dir)
    error(kind .. " render failed" .. (details ~= "" and (":\n" .. details) or ""))
  end

  local image = read_binary(output)
  local filename = string.format("pandoc-cn-%s-%s.png", kind, pandoc.sha1(source))
  pandoc.mediabag.insert(filename, "image/png", image)
  rmtree(dir)

  return pandoc.Para({
    pandoc.Image({ pandoc.Str(kind .. " diagram") }, filename)
  })
end

local function render_drawio(source)
  return render_to_mediabag("drawio", source, "drawio", function(input, output, log)
    return table.concat({
      "xvfb-run -a drawio",
      "--no-sandbox",
      "--disable-gpu",
      "--export",
      "--format png",
      "--output " .. shell_quote(output),
      shell_quote(input),
      ">" .. shell_quote(log),
      "2>&1"
    }, " ")
  end)
end

local function render_mermaid(source)
  return render_to_mediabag("mermaid", source, "mmd", function(input, output, log)
    return table.concat({
      "mmdc",
      "-p /usr/local/share/pandoc/filters/puppeteer-config.json",
      "-i " .. shell_quote(input),
      "-o " .. shell_quote(output),
      "-b white",
      ">" .. shell_quote(log),
      "2>&1"
    }, " ")
  end)
end

local function render_plantuml(source)
  return render_to_mediabag("plantuml", source, "puml", function(input, output, log)
    return table.concat({
      "plantuml",
      "-tpng",
      shell_quote(input),
      ">" .. shell_quote(log),
      "2>&1"
    }, " ")
  end)
end

function CodeBlock(el)
  if has_class(el, "drawio") then
    return render_drawio(el.text)
  end

  if has_class(el, "mermaid") then
    return render_mermaid(el.text)
  end

  if has_class(el, "plantuml") then
    return render_plantuml(el.text)
  end

  return nil
end

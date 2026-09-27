-- Runs AFTER citeproc: decorate bibliography entries, never in-text citations.
function Pandoc(doc)
  local annotations = doc.meta['reference-annotations'] or {}
  local seen, count, marked = {}, 0, 0
  local stringify = pandoc.utils.stringify
  local title = 'References and recommended reading'
  local has_header = false
  doc = doc:walk({Header = function(h)
    local text = stringify(h.content)
    if text == 'References' or text == title then
      h.content = {pandoc.Str(title)}
      has_header = true
      return h
    end
  end})
  doc = doc:walk({Div = function(div)
    if div.identifier ~= 'refs' then return nil end
    for _, entry in ipairs(div.content) do
      if entry.t == 'Div' and entry.identifier:sub(1, 4) == 'ref-' then
        count = count + 1
        local key = entry.identifier:sub(5)
        local item = annotations[key]
        if item then
          local star, text = stringify(item.interest), stringify(item.text)
          if (star ~= '*' and star ~= '**') or text:match('^%s*$') then
            error('Invalid reference annotation for ' .. key)
          end
          local replaced = false
          entry = entry:walk({Str = function(str)
            if not replaced and str.text:match('^%[%d+%]$') then
              str.text = str.text .. star .. '.'
              replaced = true
              return str
            end
          end})
          if not replaced then error('Cannot locate bibliography number for ' .. key) end
          -- Plain text is deliberate: no embedded citations or unchecked Markdown.
          entry.content:insert(pandoc.Para({pandoc.Str(text)}))
          seen[key], marked = true, marked + 1
        end
        -- Assign back because walk returns a copy.
        for i, child in ipairs(div.content) do
          if child.t == 'Div' and child.identifier == entry.identifier then
            div.content[i] = entry
            break
          end
        end
      end
    end
    if count == 0 then return div end
    local result = pandoc.List()
    if not has_header then result:insert(pandoc.Header(1, title)) end
    result:insert(pandoc.Para({pandoc.Str('Papers of particular interest, published within the period of review, have been highlighted as:')}))
    result:insert(pandoc.Para({pandoc.Str('* of special interest')}))
    result:insert(pandoc.Para({pandoc.Str('** of outstanding interest')}))
    result:insert(div)
    return result
  end})
  for key, _ in pairs(annotations) do
    if not seen[key] then
      -- A manuscript-owned annotation bank can contain entries unused in an appendix.
      io.stderr:write('paperkit: annotation not used in this document: ' .. key .. '\n')
    end
  end
  if count > 0 and marked < math.ceil(count / 10) then
    io.stderr:write(string.format('paperkit: COSB draft has %d/%d annotated references; target at least %d.\n', marked, count, math.ceil(count / 10)))
  end
  return doc
end

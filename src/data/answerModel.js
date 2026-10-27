// Presentation only. Text is rendered by React, never interpreted as HTML.
export function answerBlocks(value) {
  const lines=String(value).slice(0,30000).replaceAll('\r','').split('\n');const blocks=[]
  const cells=(line)=>line.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map((s)=>s.trim()).slice(0,12)
  for(let i=0;i<lines.length;i++){
    const line=lines[i]
    if(line.trim().startsWith('|')&&/^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$/.test(lines[i+1]||'')){
      const headers=cells(line);const rows=[];i+=2
      while(i<lines.length&&lines[i].trim().startsWith('|')&&rows.length<100){rows.push(cells(lines[i]));i++}i--
      blocks.push({kind:'table',headers,rows});continue
    }
    if(/^\s*---+\s*$/.test(line))continue
    if(/^#{1,6}\s/.test(line))blocks.push({kind:'heading',text:line.replace(/^#{1,6}\s+/,'')})
    else blocks.push({kind:'paragraph',text:line.replace(/^\s*[-*]\s+/,'• ')})
  }
  return blocks
}

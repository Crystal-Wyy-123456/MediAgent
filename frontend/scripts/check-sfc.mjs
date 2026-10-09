/**
 * 前端静态校验：用 @vue/compiler-sfc 编译所有单文件组件。
 *
 * 为什么需要它：CI 或受限环境下（例如禁止子进程启动）跑不了 Vite，
 * 但模板/脚本/样式的语法错误必须能被提前发现。
 *
 * 用法：npm run check:sfc
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse, compileScript, compileTemplate, compileStyle } from '@vue/compiler-sfc'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = process.argv[2] ? path.resolve(process.argv[2]) : path.join(here, '..', 'src')
const files = []

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full)
    else if (entry.name.endsWith('.vue')) files.push(full)
  }
}
walk(root)

let failed = 0
for (const file of files) {
  const source = fs.readFileSync(file, 'utf8')
  const id = path.basename(file)
  try {
    const { descriptor, errors } = parse(source, { filename: file })
    if (errors.length) throw new Error(errors.map((e) => e.message).join('; '))

    let bindings = {}
    if (descriptor.script || descriptor.scriptSetup) {
      bindings = compileScript(descriptor, { id, inlineTemplate: false }).bindings || {}
    }
    if (descriptor.template) {
      const res = compileTemplate({
        source: descriptor.template.content,
        filename: file,
        id,
        compilerOptions: { bindingMetadata: bindings },
      })
      if (res.errors.length) throw new Error(res.errors.map((e) => e.message || e).join('; '))
    }
    for (const style of descriptor.styles) {
      const res = compileStyle({ source: style.content, filename: file, id, scoped: style.scoped })
      if (res.errors.length) throw new Error(res.errors.map((e) => e.message || e).join('; '))
    }
    console.log(`OK   ${path.relative(root, file)}`)
  } catch (err) {
    failed += 1
    console.log(`FAIL ${path.relative(root, file)}\n     ${err.message}`)
  }
}
console.log(`\n${files.length - failed}/${files.length} 个单文件组件编译通过`)
process.exit(failed ? 1 : 0)

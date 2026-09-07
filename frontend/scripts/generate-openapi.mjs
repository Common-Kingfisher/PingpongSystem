// 从 docs/openapi-v0.2.json 生成 frontend/src/generated/openapi.d.ts。
// 使用 openapi-typescript 的 Node API，显式开启 defaultNonNullable: false，
// 使带服务端默认值的请求字段生成成 optional（而非 required）。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import openapiTS, { astToString, COMMENT_HEADER } from 'openapi-typescript'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const openapiPath = path.resolve(__dirname, '../../docs/openapi-v0.2.json')
const outputPath = path.resolve(__dirname, '../src/generated/openapi.d.ts')

const ast = await openapiTS(pathToFileURL(openapiPath), {
  defaultNonNullable: false,
})

const output = `${COMMENT_HEADER}${astToString(ast)}`

fs.mkdirSync(path.dirname(outputPath), { recursive: true })
fs.writeFileSync(outputPath, output, 'utf8')
console.log(`openapi-typescript: ${openapiPath} -> ${outputPath}`)

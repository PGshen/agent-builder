// 目录在数据模型里不是独立实体，纯粹是文件路径前缀的推导结果（见 T1.2 的 zip/flat-map 存储）。
// 新建一个空目录时，用这个占位文件把目录"落地"，否则一个文件都没有的目录在保存后会直接消失。
export const DIR_PLACEHOLDER_FILE = '.gitkeep'

export interface FileTreeFileNode {
  type: 'file'
  path: string
  name: string
}

export interface FileTreeDirNode {
  type: 'dir'
  path: string
  name: string
  children: FileTreeNode[]
}

export type FileTreeNode = FileTreeFileNode | FileTreeDirNode

/** 把 `{路径: 内容}` 的扁平 map 建成嵌套目录树；目录纯粹是路径前缀的推导结果，
 * 不作为独立实体存在——一个目录底下一个文件都没有时，它也就不存在于树里。 */
export function buildFileTree(files: Record<string, string>): FileTreeDirNode {
  const root: FileTreeDirNode = { type: 'dir', path: '', name: '', children: [] }
  const dirIndex = new Map<string, FileTreeDirNode>([['', root]])

  function ensureDir(path: string): FileTreeDirNode {
    const existing = dirIndex.get(path)
    if (existing) return existing
    const lastSlash = path.lastIndexOf('/')
    const parentPath = lastSlash === -1 ? '' : path.slice(0, lastSlash)
    const name = lastSlash === -1 ? path : path.slice(lastSlash + 1)
    const parent = ensureDir(parentPath)
    const node: FileTreeDirNode = { type: 'dir', path, name, children: [] }
    parent.children.push(node)
    dirIndex.set(path, node)
    return node
  }

  for (const path of Object.keys(files).sort()) {
    const lastSlash = path.lastIndexOf('/')
    const dirPath = lastSlash === -1 ? '' : path.slice(0, lastSlash)
    const name = lastSlash === -1 ? path : path.slice(lastSlash + 1)
    const dir = ensureDir(dirPath)
    dir.children.push({ type: 'file', path, name })
  }

  sortChildren(root)
  return root
}

function sortChildren(node: FileTreeDirNode) {
  node.children.sort((a, b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
    return a.name.localeCompare(b.name)
  })
  for (const child of node.children) {
    if (child.type === 'dir') sortChildren(child)
  }
}

export function joinPath(dirPath: string, name: string): string {
  return dirPath ? `${dirPath}/${name}` : name
}

export function basename(path: string): string {
  const lastSlash = path.lastIndexOf('/')
  return lastSlash === -1 ? path : path.slice(lastSlash + 1)
}

export function isDescendantPath(path: string, ancestorDir: string): boolean {
  return path === ancestorDir || path.startsWith(`${ancestorDir}/`)
}

export function addFile(
  files: Record<string, string>,
  path: string,
  content = ''
): Record<string, string> {
  return { ...files, [path]: content }
}

export function deleteFile(files: Record<string, string>, path: string): Record<string, string> {
  const next = { ...files }
  delete next[path]
  return next
}

export function deleteDir(files: Record<string, string>, dirPath: string): Record<string, string> {
  const next = { ...files }
  for (const path of Object.keys(files)) {
    if (isDescendantPath(path, dirPath)) delete next[path]
  }
  return next
}

export function renameFile(
  files: Record<string, string>,
  oldPath: string,
  newPath: string
): Record<string, string> {
  if (oldPath === newPath || !(oldPath in files)) return files
  const next = { ...files }
  const content = next[oldPath]
  delete next[oldPath]
  next[newPath] = content
  return next
}

/** 目录改名/移动：把所有以 oldDirPath 为前缀的文件路径整体替换成 newDirPath 前缀。 */
export function renameDir(
  files: Record<string, string>,
  oldDirPath: string,
  newDirPath: string
): Record<string, string> {
  if (oldDirPath === newDirPath) return files
  const next = { ...files }
  for (const path of Object.keys(files)) {
    if (isDescendantPath(path, oldDirPath)) {
      const rest = path.slice(oldDirPath.length)
      delete next[path]
      next[`${newDirPath}${rest}`] = files[path]
    }
  }
  return next
}

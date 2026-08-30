import { type DragEvent, type KeyboardEvent, type ReactNode, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  File as FileIcon,
  FilePlus,
  Folder,
  FolderOpen,
  FolderPlus,
  Pencil,
  Trash2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  addFile,
  basename,
  buildFileTree,
  deleteDir,
  deleteFile,
  DIR_PLACEHOLDER_FILE,
  isDescendantPath,
  joinPath,
  renameDir,
  renameFile,
  type FileTreeDirNode,
  type FileTreeNode,
} from '@/lib/fileTree'

interface SkillFileTreeProps {
  files: Record<string, string>
  selectedPath: string | null
  onSelectFile: (path: string | null) => void
  onFilesChange: (files: Record<string, string>) => void
}

export function SkillFileTree({ files, selectedPath, onSelectFile, onFilesChange }: SkillFileTreeProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [renamingPath, setRenamingPath] = useState<string | null>(null)
  const [creatingInDir, setCreatingInDir] = useState<string | null>(null)
  const [creatingKind, setCreatingKind] = useState<'file' | 'dir'>('file')
  const [dragOverDir, setDragOverDir] = useState<string | null>(null)
  const [draggingPath, setDraggingPath] = useState<string | null>(null)

  const root = buildFileTree(files)

  function toggleCollapsed(path: string) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  function isFile(path: string): boolean {
    return path in files
  }

  function startRename(path: string) {
    setCreatingInDir(null)
    setRenamingPath(path)
  }

  function commitRename(oldPath: string, rawValue: string) {
    setRenamingPath(null)
    const newPath = rawValue.trim().replace(/^\/+|\/+$/g, '')
    if (!newPath || newPath === oldPath) return
    const next = isFile(oldPath) ? renameFile(files, oldPath, newPath) : renameDir(files, oldPath, newPath)
    onFilesChange(next)
    if (selectedPath && isDescendantPath(selectedPath, oldPath)) {
      onSelectFile(selectedPath === oldPath ? newPath : newPath + selectedPath.slice(oldPath.length))
    }
  }

  function handleDelete(node: FileTreeNode) {
    const label = node.type === 'dir' ? `文件夹「${node.path}」（及其下所有文件）` : `文件「${node.path}」`
    if (!window.confirm(`删除${label}？`)) return
    const next = node.type === 'dir' ? deleteDir(files, node.path) : deleteFile(files, node.path)
    onFilesChange(next)
    if (selectedPath && isDescendantPath(selectedPath, node.path)) {
      onSelectFile(null)
    }
  }

  function startCreate(dirPath: string, kind: 'file' | 'dir') {
    setRenamingPath(null)
    setCollapsed((prev) => {
      if (!prev.has(dirPath)) return prev
      const next = new Set(prev)
      next.delete(dirPath)
      return next
    })
    setCreatingKind(kind)
    setCreatingInDir(dirPath)
  }

  function commitCreate(dirPath: string, rawValue: string) {
    setCreatingInDir(null)
    const name = rawValue.trim().replace(/^\/+|\/+$/g, '')
    if (!name) return

    if (creatingKind === 'dir') {
      // 目录不是独立实体，靠里面放一个占位文件把它"落地"，否则空目录保存后就不存在了
      const path = joinPath(joinPath(dirPath, name), DIR_PLACEHOLDER_FILE)
      if (path in files) return
      onFilesChange(addFile(files, path))
      onSelectFile(path)
      return
    }

    const path = joinPath(dirPath, name)
    if (path in files) return
    onFilesChange(addFile(files, path))
    onSelectFile(path)
  }

  function handleDrop(sourcePath: string, targetDirPath: string) {
    setDragOverDir(null)
    setDraggingPath(null)
    if (sourcePath === targetDirPath) return
    if (!isFile(sourcePath) && isDescendantPath(targetDirPath, sourcePath)) return // 不能拖进自己的子目录

    const name = basename(sourcePath)
    const newPath = joinPath(targetDirPath, name)
    if (newPath === sourcePath) return

    const next = isFile(sourcePath) ? renameFile(files, sourcePath, newPath) : renameDir(files, sourcePath, newPath)
    onFilesChange(next)
    if (selectedPath && isDescendantPath(selectedPath, sourcePath)) {
      onSelectFile(selectedPath === sourcePath ? newPath : newPath + selectedPath.slice(sourcePath.length))
    }
  }

  return (
    <div className="flex flex-col text-sm">
      <TreeRow
        depth={0}
        icon={<FolderOpen className="size-3.5 text-muted-foreground" />}
        label={<span className="text-muted-foreground">根目录</span>}
        isDragOver={dragOverDir === ''}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOverDir('')
        }}
        onDragLeave={() => setDragOverDir(null)}
        onDrop={(e) => {
          e.preventDefault()
          const sourcePath = e.dataTransfer.getData('text/plain')
          if (sourcePath) handleDrop(sourcePath, '')
        }}
        actions={
          <>
            <RowActionButton label="在根目录新建文件" onClick={() => startCreate('', 'file')}>
              <FilePlus className="size-3.5" />
            </RowActionButton>
            <RowActionButton label="在根目录新建目录" onClick={() => startCreate('', 'dir')}>
              <FolderPlus className="size-3.5" />
            </RowActionButton>
          </>
        }
      />
      <DirRow
        node={root}
        depth={0}
        collapsed={collapsed}
        renamingPath={renamingPath}
        creatingInDir={creatingInDir}
        creatingKind={creatingKind}
        dragOverDir={dragOverDir}
        draggingPath={draggingPath}
        selectedPath={selectedPath}
        isFile={isFile}
        onToggleCollapsed={toggleCollapsed}
        onSelectFile={onSelectFile}
        onStartRename={startRename}
        onCommitRename={commitRename}
        onCancelRename={() => setRenamingPath(null)}
        onStartCreate={startCreate}
        onCommitCreate={commitCreate}
        onCancelCreate={() => setCreatingInDir(null)}
        onDelete={handleDelete}
        onDragStart={setDraggingPath}
        onDragOverDir={setDragOverDir}
        onDrop={handleDrop}
      />
    </div>
  )
}

interface RowSharedProps {
  collapsed: Set<string>
  renamingPath: string | null
  creatingInDir: string | null
  creatingKind: 'file' | 'dir'
  dragOverDir: string | null
  draggingPath: string | null
  selectedPath: string | null
  isFile: (path: string) => boolean
  onToggleCollapsed: (path: string) => void
  onSelectFile: (path: string | null) => void
  onStartRename: (path: string) => void
  onCommitRename: (oldPath: string, value: string) => void
  onCancelRename: () => void
  onStartCreate: (dirPath: string, kind: 'file' | 'dir') => void
  onCommitCreate: (dirPath: string, value: string) => void
  onCancelCreate: () => void
  onDelete: (node: FileTreeNode) => void
  onDragStart: (path: string | null) => void
  onDragOverDir: (path: string | null) => void
  onDrop: (sourcePath: string, targetDirPath: string) => void
}

function DirRow({ node, depth, ...shared }: { node: FileTreeDirNode; depth: number } & RowSharedProps) {
  const isRoot = node.path === ''
  const isExpanded = !shared.collapsed.has(node.path)
  const isRenaming = shared.renamingPath === node.path
  const isDragOver = shared.dragOverDir === node.path

  return (
    <div>
      {!isRoot && (
        <TreeRow
          depth={depth}
          draggable
          isDragOver={isDragOver}
          onDragStart={(e) => {
            e.dataTransfer.setData('text/plain', node.path)
            shared.onDragStart(node.path)
          }}
          onDragEnd={() => shared.onDragStart(null)}
          onDragOver={(e) => {
            e.preventDefault()
            shared.onDragOverDir(node.path)
          }}
          onDragLeave={() => shared.onDragOverDir(null)}
          onDrop={(e) => {
            e.preventDefault()
            const sourcePath = e.dataTransfer.getData('text/plain')
            if (sourcePath) shared.onDrop(sourcePath, node.path)
          }}
          icon={
            <button
              type="button"
              onClick={() => shared.onToggleCollapsed(node.path)}
              className="flex items-center text-muted-foreground"
              aria-label={isExpanded ? '折叠' : '展开'}
            >
              {isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              {isExpanded ? (
                <FolderOpen className="ml-0.5 size-3.5" />
              ) : (
                <Folder className="ml-0.5 size-3.5" />
              )}
            </button>
          }
          label={
            isRenaming ? (
              <InlineInput
                defaultValue={node.path}
                onCommit={(value) => shared.onCommitRename(node.path, value)}
                onCancel={shared.onCancelRename}
              />
            ) : (
              <button
                type="button"
                className="truncate text-left"
                onClick={() => shared.onToggleCollapsed(node.path)}
              >
                {node.name}
              </button>
            )
          }
          actions={
            !isRenaming && (
              <>
                <RowActionButton
                  label={`在 ${node.name} 下新建文件`}
                  onClick={() => shared.onStartCreate(node.path, 'file')}
                >
                  <FilePlus className="size-3.5" />
                </RowActionButton>
                <RowActionButton
                  label={`在 ${node.name} 下新建目录`}
                  onClick={() => shared.onStartCreate(node.path, 'dir')}
                >
                  <FolderPlus className="size-3.5" />
                </RowActionButton>
                <RowActionButton label="重命名/移动" onClick={() => shared.onStartRename(node.path)}>
                  <Pencil className="size-3.5" />
                </RowActionButton>
                <RowActionButton label="删除" onClick={() => shared.onDelete(node)}>
                  <Trash2 className="size-3.5" />
                </RowActionButton>
              </>
            )
          }
        />
      )}

      {(isRoot || isExpanded) && (
        <div
          onDragOver={
            isRoot
              ? (e) => {
                  e.preventDefault()
                  shared.onDragOverDir('')
                }
              : undefined
          }
          onDragLeave={isRoot ? () => shared.onDragOverDir(null) : undefined}
          onDrop={
            isRoot
              ? (e) => {
                  e.preventDefault()
                  const sourcePath = e.dataTransfer.getData('text/plain')
                  if (sourcePath) shared.onDrop(sourcePath, '')
                }
              : undefined
          }
          className={cn(isRoot && shared.dragOverDir === '' && 'rounded bg-accent/40')}
        >
          {node.children.map((child) =>
            child.type === 'dir' ? (
              <DirRow key={child.path} node={child} depth={depth + 1} {...shared} />
            ) : (
              <FileRow key={child.path} path={child.path} name={child.name} depth={depth + 1} {...shared} />
            )
          )}
          {shared.creatingInDir === node.path && (
            <TreeRow
              depth={depth + 1}
              icon={
                shared.creatingKind === 'dir' ? (
                  <Folder className="size-3.5 text-muted-foreground" />
                ) : (
                  <FileIcon className="size-3.5 text-muted-foreground" />
                )
              }
              label={
                <InlineInput
                  defaultValue=""
                  placeholder={shared.creatingKind === 'dir' ? '目录名' : '文件名，可含 / 建子目录'}
                  onCommit={(value) => shared.onCommitCreate(node.path, value)}
                  onCancel={shared.onCancelCreate}
                />
              }
            />
          )}
        </div>
      )}
    </div>
  )
}

function FileRow({
  path,
  name,
  depth,
  ...shared
}: { path: string; name: string; depth: number } & RowSharedProps) {
  const isRenaming = shared.renamingPath === path
  const isSelected = shared.selectedPath === path
  const isDragging = shared.draggingPath === path

  return (
    <TreeRow
      depth={depth}
      selected={isSelected}
      draggable
      dimmed={isDragging}
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', path)
        shared.onDragStart(path)
      }}
      onDragEnd={() => shared.onDragStart(null)}
      icon={<FileIcon className="size-3.5 text-muted-foreground" />}
      label={
        isRenaming ? (
          <InlineInput
            defaultValue={path}
            onCommit={(value) => shared.onCommitRename(path, value)}
            onCancel={shared.onCancelRename}
          />
        ) : (
          <button type="button" className="truncate text-left" onClick={() => shared.onSelectFile(path)}>
            {name}
          </button>
        )
      }
      actions={
        !isRenaming && (
          <>
            <RowActionButton label="重命名/移动" onClick={() => shared.onStartRename(path)}>
              <Pencil className="size-3.5" />
            </RowActionButton>
            <RowActionButton label="删除" onClick={() => shared.onDelete({ type: 'file', path, name })}>
              <Trash2 className="size-3.5" />
            </RowActionButton>
          </>
        )
      }
    />
  )
}

function TreeRow({
  depth,
  icon,
  label,
  actions,
  selected,
  dimmed,
  draggable,
  isDragOver,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  depth: number
  icon: ReactNode
  label: ReactNode
  actions?: ReactNode
  selected?: boolean
  dimmed?: boolean
  draggable?: boolean
  isDragOver?: boolean
  onDragStart?: (e: DragEvent) => void
  onDragEnd?: () => void
  onDragOver?: (e: DragEvent) => void
  onDragLeave?: () => void
  onDrop?: (e: DragEvent) => void
}) {
  return (
    <div
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={cn(
        'group flex items-center gap-1.5 rounded px-1.5 py-1 hover:bg-muted',
        selected && 'bg-muted font-medium',
        isDragOver && 'bg-accent/60 outline outline-1 outline-accent-foreground/30',
        dimmed && 'opacity-40'
      )}
      style={{ paddingLeft: `${depth * 14 + 6}px` }}
    >
      {icon}
      <span className="min-w-0 flex-1 font-mono text-xs">{label}</span>
      <span className="hidden items-center gap-0.5 group-hover:flex">{actions}</span>
    </div>
  )
}

function RowActionButton({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      className="rounded p-0.5 text-muted-foreground hover:bg-background hover:text-foreground"
    >
      {children}
    </button>
  )
}

function InlineInput({
  defaultValue,
  placeholder,
  onCommit,
  onCancel,
}: {
  defaultValue: string
  placeholder?: string
  onCommit: (value: string) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState(defaultValue)

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      onCommit(value)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onCancel()
    }
  }

  return (
    <input
      autoFocus
      value={value}
      placeholder={placeholder}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={handleKeyDown}
      onBlur={() => onCommit(value)}
      onClick={(e) => e.stopPropagation()}
      className="w-full rounded border border-ring bg-background px-1 py-0.5 font-mono text-xs outline-none"
    />
  )
}

/** UI 仅消费由 OpenAPI 生成的团队运行态类型，避免维护第二份 DTO。 */
export type {
  TeamTieDetail as TeamTieView,
  TeamRubber as TeamRubberView,
  TeamLineupOptions,
} from '../api'

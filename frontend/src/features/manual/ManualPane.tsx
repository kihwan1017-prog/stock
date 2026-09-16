"use client";

import {
  Affix,
  Anchor,
  Button,
  Card,
  Collapse,
  Empty,
  Flex,
  Input,
  Space,
  Typography,
} from "antd";
import Link from "next/link";
import { useMemo, useState } from "react";

import { ManualStatusBadge } from "./ManualStatusBadge";
import type { ManualSection } from "./manualTypes";

interface ManualPaneProps {
  sections: ManualSection[];
  searchPlaceholder?: string;
}

export function ManualPane({
  sections,
  searchPlaceholder = "메뉴·키워드 검색",
}: ManualPaneProps) {
  const [query, setQuery] = useState("");
  const [activeKeys, setActiveKeys] = useState<string[]>(
    sections.map((section) => section.id),
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sections;
    return sections.filter((section) => {
      const haystack = [
        section.title,
        section.menuPath,
        section.route,
        section.purpose,
        ...(section.steps ?? []),
        ...(section.buttons ?? []),
        ...(section.errors ?? []),
        ...(section.notes ?? []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [query, sections]);

  const expandAll = () => setActiveKeys(filtered.map((s) => s.id));
  const collapseAll = () => setActiveKeys([]);

  if (!sections.length) {
    return <Empty description="매뉴얼 섹션이 없습니다." />;
  }

  return (
    <Flex gap={16} align="flex-start" wrap="wrap">
      <Affix offsetTop={80}>
        <Card
          size="small"
          title="목차"
          style={{ width: 260, maxHeight: "70vh", overflow: "auto" }}
        >
          <Anchor
            affix={false}
            items={filtered.map((section) => ({
              key: section.id,
              href: `#${section.id}`,
              title: section.title,
            }))}
          />
        </Card>
      </Affix>

      <div style={{ flex: 1, minWidth: 280 }}>
        <Space wrap style={{ marginBottom: 12 }}>
          <Input.Search
            allowClear
            placeholder={searchPlaceholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: 280 }}
          />
          <Button size="small" onClick={expandAll}>
            모두 펼치기
          </Button>
          <Button size="small" onClick={collapseAll}>
            모두 접기
          </Button>
          <Typography.Text type="secondary">
            {filtered.length}/{sections.length} 섹션
          </Typography.Text>
        </Space>

        {filtered.length === 0 ? (
          <Empty description="검색 결과가 없습니다." />
        ) : (
          <Collapse
            activeKey={activeKeys}
            onChange={(keys) =>
              setActiveKeys(Array.isArray(keys) ? keys.map(String) : [String(keys)])
            }
            items={filtered.map((section) => ({
              key: section.id,
              label: (
                <Space wrap id={section.id}>
                  <span>{section.title}</span>
                  <ManualStatusBadge status={section.status} />
                </Space>
              ),
              children: <ManualSectionBody section={section} />,
            }))}
          />
        )}
      </div>
    </Flex>
  );
}

function ManualSectionBody({ section }: { section: ManualSection }) {
  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      {section.menuPath ? (
        <Typography.Text>
          <Typography.Text strong>진입 경로: </Typography.Text>
          {section.menuPath}
          {section.route ? (
            <>
              {" · "}
              <Link href={section.route}>{section.route}</Link>
            </>
          ) : null}
        </Typography.Text>
      ) : null}

      <Typography.Paragraph style={{ marginBottom: 0 }}>
        <Typography.Text strong>목적: </Typography.Text>
        {section.purpose}
      </Typography.Paragraph>

      {section.prerequisites?.length ? (
        <FieldList title="선행 조건" items={section.prerequisites} />
      ) : null}
      <FieldList title="사용 순서" items={section.steps} ordered />
      {section.buttons?.length ? (
        <FieldList title="주요 버튼" items={section.buttons} />
      ) : null}
      {section.normalState?.length ? (
        <FieldList title="정상 상태" items={section.normalState} />
      ) : null}
      {section.errors?.length ? (
        <FieldList title="오류 발생 시 확인" items={section.errors} />
      ) : null}

      <Typography.Paragraph style={{ marginBottom: 0 }}>
        <Typography.Text strong>실거래 영향: </Typography.Text>
        {section.liveImpact}
      </Typography.Paragraph>

      {section.nextSteps?.length ? (
        <FieldList title="다음 단계" items={section.nextSteps} />
      ) : null}
      {section.notes?.length ? (
        <FieldList title="참고" items={section.notes} />
      ) : null}
    </Space>
  );
}

function FieldList({
  title,
  items,
  ordered,
}: {
  title: string;
  items: string[];
  ordered?: boolean;
}) {
  const ListTag = ordered ? "ol" : "ul";
  return (
    <div>
      <Typography.Text strong>{title}</Typography.Text>
      <ListTag style={{ margin: "4px 0 0", paddingLeft: 20 }}>
        {items.map((item) => (
          <li key={`${title}-${item}`}>
            <Typography.Text>{item}</Typography.Text>
          </li>
        ))}
      </ListTag>
    </div>
  );
}

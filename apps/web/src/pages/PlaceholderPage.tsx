import { Empty } from "antd";

import { PageHeader } from "../components/PageHeader/PageHeader";

interface PlaceholderPageProps {
  title: string;
  description: string;
}

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <section>
      <PageHeader title={title} description={description} />
      <div className="placeholder-panel">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="M01 基础页面，功能尚未实现"
        />
      </div>
    </section>
  );
}

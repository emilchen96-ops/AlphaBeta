import { Button, Result } from "antd";
import { useNavigate } from "react-router-dom";

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <Result
      status="404"
      title="页面不存在"
      subTitle="请通过左侧导航进入 AlphaDesk 的 M01 基础页面。"
      extra={
        <Button type="primary" onClick={() => void navigate("/")}>
          返回总览
        </Button>
      }
    />
  );
}

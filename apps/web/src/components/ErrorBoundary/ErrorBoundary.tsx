import { Alert, Button } from "antd";
import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(): void {
    // The UI deliberately avoids exposing stack traces. A remote sink may be added later.
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="fatal-error">
          <Alert
            type="error"
            showIcon
            title="页面出现异常"
            description="请刷新页面；若问题持续，请检查本地服务日志。"
            action={
              <Button onClick={() => window.location.reload()}>刷新页面</Button>
            }
          />
        </div>
      );
    }
    return this.props.children;
  }
}
